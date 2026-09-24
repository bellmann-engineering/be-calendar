"""
E-Mail-Versand über SMTP – fehlertolerant und ohne den HTTP-Request zu blockieren.

Was macht diese Datei?
    * ``send_email()``   – baut eine MIME-Mail (Text + optional HTML) und schickt sie
                           per SMTP mit STARTTLS. Fehler werden geloggt, nie geworfen.
    * ``send_async()``   – dasselbe, aber in einem Hintergrund-Thread (ThreadPool), damit
                           der Benutzer nicht auf den SMTP-Server warten muss.
    * ``queue_email()``  – merkt eine Mail vor; verschickt wird sie erst, wenn die
                           aktuelle DB-Transaktion erfolgreich committet wurde.

Wer benutzt sie?
    NotificationService (Benachrichtigungen), AuthService (Passwort-Reset),
    UserService (Einladungen beim CSV-Import).

Womit spricht sie?
    Mit dem SMTP-Server aus der Konfiguration (SMTP_SERVER, SMTP_PORT, SMTP_USER,
    SMTP_PASSWORD). Ist SMTP nicht konfiguriert, wird der Versand still übersprungen.

Warum ein ThreadPool und kein Celery/RQ?
    Für das aktuelle Volumen (einzelne Mails pro Aktion) genügt ein kleiner Pool pro
    Gunicorn-Prozess ohne zusätzliche Infrastruktur. Wächst das Volumen oder müssen
    Mails Neustarts überleben, ist eine echte Queue (RQ + Redis) der nächste Schritt.
"""

import logging
import smtplib
from concurrent.futures import ThreadPoolExecutor
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from threading import Lock
from typing import Any

from flask import current_app

from app.utils.transaction import call_after_commit

logger = logging.getLogger(__name__)

# Ein Pool pro Prozess, erst beim ersten Bedarf erzeugt (nach dem Fork durch Gunicorn).
_executor: ThreadPoolExecutor | None = None
_executor_lock = Lock()


def _get_executor() -> ThreadPoolExecutor:
    """Erzeugt den Thread-Pool threadsicher beim ersten Aufruf (Lazy Singleton)."""
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mail")
        return _executor


def _smtp_settings() -> dict[str, Any]:
    """Kopiert die SMTP-Einstellungen aus der App-Konfiguration in ein einfaches dict.

    Der Hintergrund-Thread hat keinen Flask-App-Kontext mehr – deshalb werden die Werte
    hier im Request-Thread eingesammelt und als Argument weitergereicht.
    """
    cfg = current_app.config
    return {
        "server": cfg.get("SMTP_SERVER"),
        "port": int(cfg.get("SMTP_PORT", 587)),
        "user": cfg.get("SMTP_USER"),
        "password": cfg.get("SMTP_PASSWORD"),
        "sender": cfg.get("MAIL_DEFAULT_SENDER") or cfg.get("SMTP_USER"),
    }


def _deliver(
    settings: dict[str, Any],
    to_email: str,
    subject: str,
    body_text: str,
    html_body: str | None,
) -> bool:
    """Der eigentliche SMTP-Versand (läuft im Request- ODER im Hintergrund-Thread)."""
    if not settings["server"] or not settings["user"] or not settings["password"]:
        logger.info("SMTP nicht konfiguriert – E-Mail an %s übersprungen.", to_email)
        return False

    # 'alternative': Mail-Programme zeigen HTML, wenn möglich, sonst den Text-Teil.
    msg = MIMEMultipart("alternative")
    msg["From"] = settings["sender"]
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        # timeout=10 gilt pro Socket-Operation (connect, starttls, login, send).
        with smtplib.SMTP(settings["server"], settings["port"], timeout=10) as smtp:
            smtp.starttls()
            smtp.login(settings["user"], settings["password"])
            smtp.send_message(msg)
        logger.info("E-Mail an %s versendet: %s", to_email, subject)
        return True
    except (smtplib.SMTPException, OSError):
        logger.exception("E-Mail-Versand an %s fehlgeschlagen", to_email)
        return False


class EmailService:
    """Service-Schicht für den fehlergeschützten E-Mail-Versand via SMTP."""

    @staticmethod
    def send_email(
        to_email: str, subject: str, body_text: str, html_body: str | None = None
    ) -> bool:
        """Versendet sofort und synchron. Gibt True bei Erfolg zurück, wirft nie."""
        return _deliver(_smtp_settings(), to_email, subject, body_text, html_body)

    @staticmethod
    def send_async(
        to_email: str, subject: str, body_text: str, html_body: str | None = None
    ) -> None:
        """Versendet im Hintergrund (oder synchron, wenn MAIL_ASYNC=False, z. B. in Tests)."""
        settings = _smtp_settings()
        if not current_app.config.get("MAIL_ASYNC", True):
            _deliver(settings, to_email, subject, body_text, html_body)
            return
        _get_executor().submit(_deliver, settings, to_email, subject, body_text, html_body)

    @staticmethod
    def queue_email(
        to_email: str, subject: str, body_text: str, html_body: str | None = None
    ) -> None:
        """Verschickt die Mail erst NACH dem nächsten erfolgreichen ``db.session.commit()``.

        Wird die Transaktion zurückgerollt, geht keine Mail raus.
        """
        # Einstellungen JETZT (im App-Kontext) einsammeln, versendet wird später.
        settings = _smtp_settings()
        use_async = current_app.config.get("MAIL_ASYNC", True)

        def _send() -> None:
            if use_async:
                _get_executor().submit(_deliver, settings, to_email, subject, body_text, html_body)
            else:
                _deliver(settings, to_email, subject, body_text, html_body)

        call_after_commit(_send)
