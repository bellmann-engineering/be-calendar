"""
Authentifizierung: Login-Prüfung und Passwort-Reset per signiertem Einmal-Link.

Was macht diese Datei?
    * ``authenticate_user()``       – prüft E-Mail + Passwort, liefert den User oder None.
    * ``authenticate_proxy_user()`` – User zur E-Mail aus Authelia (Single Sign-on).
    * ``generate_password_token()`` – erzeugt einen signierten, zeitlich begrenzten Token
                                      für "Passwort vergessen" und Einladungen.
    * ``request_password_reset()``  – verschickt den Reset-Link per E-Mail.
    * ``reset_password()``          – prüft den Token und setzt das neue Passwort.
    * ``validate_password()``       – zentrale Passwort-Richtlinie (Mindestlänge).

Wer benutzt sie?
    ``app/routes/auth_routes.py`` (Login, Forgot/Reset) und UserService (Einladungen).
    Das Setzen der JWT-Cookies passiert in der Route, nicht hier.

Wie funktioniert der Einmal-Token? (itsdangerous, kommt mit Flask)
    Der Token enthält die User-ID, den Zweck und einen Fingerabdruck des AKTUELLEN
    Passwort-Hashes – signiert mit SECRET_KEY. Sobald das Passwort geändert wurde, passt
    der Fingerabdruck nicht mehr: Der Link ist damit automatisch nur EINMAL gültig,
    ganz ohne zusätzliche Datenbanktabelle.
"""

import hashlib
import logging
import secrets

from flask import current_app, render_template
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.models import AuditLog, User
from app.services.email_service import EmailService
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

# Salt trennt diese Tokens von anderen itsdangerous-Signaturen – kein Geheimnis.
_TOKEN_SALT = "bellmann-password-token"  # noqa: S105
PURPOSE_RESET = "reset"
PURPOSE_INVITE = "invite"

# Dummy-Hash für Benutzer, die es nicht gibt: So dauert ein Login-Versuch mit unbekannter
# E-Mail genauso lange wie einer mit falschem Passwort (Schutz vor User-Enumeration über
# die Antwortzeit). Wird beim ersten Gebrauch erzeugt.
_DUMMY_HASH: str | None = None


def _password_fingerprint(user: User) -> str:
    """Kurzer Fingerabdruck des Passwort-Hashes (macht Tokens einmalig verwendbar)."""
    return hashlib.sha256(user.password_hash.encode("utf-8")).hexdigest()[:16]


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_TOKEN_SALT)


class AuthService:
    """Service-Schicht für Authentifizierung und Passwort-Tokens."""

    @staticmethod
    def authenticate_user(email: str, password: str) -> User | None:
        """Prüft Zugangsdaten. Gibt den aktiven User zurück oder None (gleiche Antwort für
        "unbekannt", "falsches Passwort" und "deaktiviert" – verrät nichts)."""
        global _DUMMY_HASH
        normalized = (email or "").strip().lower()
        user = User.query.filter_by(email=normalized, is_active=True).first()
        if user is None:
            if _DUMMY_HASH is None:
                _DUMMY_HASH = generate_password_hash("dummy-password-for-timing")
            check_password_hash(_DUMMY_HASH, password)
            return None
        if not check_password_hash(user.password_hash, password):
            return None
        return user

    @staticmethod
    def authenticate_proxy_user(email: str | None) -> User | None:
        """Aktiver User zur E-Mail, die Authelia bereits geprüft hat (ohne Passwort).

        Groß-/Kleinschreibung spielt keine Rolle: Authelia liefert die Adresse so, wie sie
        im Verzeichnis steht, in der App kann sie anders geschrieben sein.
        """
        normalized = (email or "").strip().lower()
        if not normalized:
            return None
        return User.query.filter(
            func.lower(User.email) == normalized, User.is_active.is_(True)
        ).first()

    @staticmethod
    def random_password() -> str:
        """Kryptografisch sicheres Zufallspasswort (z. B. Platzhalter beim CSV-Import)."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def validate_password(password: object) -> str | None:
        """Passwort-Richtlinie. Gibt eine Fehlermeldung zurück oder None, wenn OK."""
        min_len = current_app.config.get("PASSWORD_MIN_LENGTH", 10)
        if not isinstance(password, str) or len(password) < min_len:
            return f"Das Passwort muss mindestens {min_len} Zeichen lang sein."
        if len(password) > 256:
            return "Das Passwort ist zu lang (max. 256 Zeichen)."
        return None

    # ------------------------------------------------------------------ Tokens
    @staticmethod
    def generate_password_token(user: User, purpose: str = PURPOSE_RESET) -> str:
        """Signierter Token mit User-ID, Zweck und Passwort-Fingerabdruck."""
        payload = {"uid": user.id, "p": purpose, "fp": _password_fingerprint(user)}
        return _serializer().dumps(payload)

    @staticmethod
    def build_reset_url(token: str) -> str:
        """Absolute URL zur Reset-Seite (Basis-URL aus APP_BASE_URL)."""
        return f"{current_app.config['APP_BASE_URL']}/reset-password?token={token}"

    @staticmethod
    def _load_token(token: str) -> User | None:
        """Prüft Signatur, Ablaufzeit (je nach Zweck) und Fingerabdruck."""
        cfg = current_app.config
        try:
            # Erst mit der längsten erlaubten Laufzeit laden, dann je Zweck genauer prüfen.
            payload, issued_at = _serializer().loads(
                token, max_age=cfg["INVITE_MAX_AGE"], return_timestamp=True
            )
        except SignatureExpired:
            return None
        except BadSignature:
            return None

        if not isinstance(payload, dict):
            return None
        max_age = (
            cfg["INVITE_MAX_AGE"]
            if payload.get("p") == PURPOSE_INVITE
            else cfg["PASSWORD_RESET_MAX_AGE"]
        )
        if (utc_now() - issued_at).total_seconds() > max_age:
            return None

        user = db.session.get(User, payload.get("uid"))
        if user is None or not user.is_active:
            return None
        if payload.get("fp") != _password_fingerprint(user):
            return None  # Passwort wurde inzwischen geändert -> Link verbraucht
        return user

    # ------------------------------------------------------------------ Flows
    @staticmethod
    def request_password_reset(email: str) -> None:
        """Verschickt (falls der Benutzer existiert und aktiv ist) einen Reset-Link.

        Gibt bewusst nichts zurück: Die Route antwortet immer gleich, damit niemand
        herausfinden kann, welche E-Mail-Adressen registriert sind.
        """
        user = User.query.filter_by(email=(email or "").strip().lower()).first()
        if not user or not user.is_active:
            logger.info("Passwort-Reset für unbekannte/inaktive Adresse angefordert.")
            return

        reset_url = AuthService.build_reset_url(AuthService.generate_password_token(user))
        minutes = current_app.config["PASSWORD_RESET_MAX_AGE"] // 60
        html_body = render_template(
            "email/forgot_password.html", user=user, reset_url=reset_url, minutes=minutes
        )
        text_body = (
            f"Hallo {user.first_name},\n\n"
            f"über folgenden Link kannst du ein neues Passwort festlegen "
            f"(gültig für {minutes} Minuten):\n{reset_url}\n\n"
            "Falls du das nicht angefordert hast, ignoriere diese E-Mail."
        )
        # Keine DB-Änderung -> kein Commit -> direkt (asynchron) senden.
        EmailService.send_async(user.email, "Passwort zurücksetzen", text_body, html_body)

    @staticmethod
    def reset_password(token: str, new_password: str) -> tuple[bool, str | None, int]:
        """Setzt ein neues Passwort, wenn der Token gültig ist."""
        if not isinstance(token, str) or not token:
            return False, "Der Link ist ungültig.", 400
        password_error = AuthService.validate_password(new_password)
        if password_error:
            return False, password_error, 400

        user = AuthService._load_token(token)
        if user is None:
            return False, "Der Link ist ungültig oder abgelaufen.", 400

        user.password_hash = generate_password_hash(new_password)
        db.session.add(
            AuditLog(
                user_id=user.id,
                action="PASSWORD_RESET",
                details_json={"user_id": user.id},
            )
        )
        db.session.commit()
        return True, None, 200
