import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app


class EmailService:
    """Service-Schicht für den fehlergeschützten E-Mail-Versand via SMTP."""

    @staticmethod
    def send_email(
        to_email: str, subject: str, body_text: str, html_body: str = None
    ) -> bool:
        """Versendet eine E-Mail. Fehler beim Versand blockieren die Anwendung nicht."""
        server = current_app.config.get("SMTP_SERVER")
        port = current_app.config.get("SMTP_PORT", 587)
        user = current_app.config.get("SMTP_USER")
        password = current_app.config.get("SMTP_PASSWORD")
        sender = current_app.config.get("MAIL_DEFAULT_SENDER", user)

        if not server or not user or not password:
            # SMTP nicht konfiguriert - überspringen ohne Absturz
            return False

        try:
            # 'alternative' verwenden, um Plain-Text und HTML gleichzeitig zu senden
            msg = MIMEMultipart("alternative")
            msg["From"] = sender
            msg["To"] = to_email
            msg["Subject"] = subject

            # 1. Plain-Text immer als Fallback anhängen
            msg.attach(MIMEText(body_text, "plain", "utf-8"))

            # 2. Wenn ein html_body übergeben wird, diesen ebenfalls anhängen
            if html_body:
                msg.attach(MIMEText(html_body, "html", "utf-8"))

            with smtplib.SMTP(server, int(port), timeout=10) as smtp_server:
                smtp_server.starttls()
                smtp_server.login(user, password)
                smtp_server.send_message(msg)
            return True
        except Exception:
            # Fehler protokollieren, aber HTTP-Request nicht abbrechen
            return False
