"""
Zentrale Konfiguration der Flask-Anwendung (12-Factor-Prinzip).

Was macht diese Datei?
    Sie liest ALLE Einstellungen aus Umgebungsvariablen (bzw. aus der ``.env``-Datei)
    und bündelt sie in Konfigurationsklassen – eine pro Umgebung:

    * ``DevelopmentConfig`` – lokales Entwickeln (``flask run``), DEBUG erlaubt.
    * ``ProductionConfig``  – Docker/Gunicorn. DEBUG ist hart auf ``False`` verdrahtet
      und fehlende oder schwache Secrets lassen den Start absichtlich scheitern.
    * ``TestingConfig``     – pytest, eigene Test-Datenbank, Rate-Limit aus.

Wer benutzt sie?
    ``app/__init__.py::create_app()`` ruft ``get_config()`` auf und lädt die passende
    Klasse per ``app.config.from_object(...)``.

Wovon hängt sie ab?
    * ``python-dotenv`` (lädt ``.env`` in ``os.environ``)
    * Umgebungsvariable ``APP_ENV`` (``production`` | ``development`` | ``testing``)
      – wird in ``docker-compose.yml`` fest auf ``production`` gesetzt.

Wichtig: In dieser Datei stehen KEINE echten Zugangsdaten. Alles kommt aus ``.env``.
"""

import os
from datetime import timedelta

from dotenv import load_dotenv

from app.utils.url_prefix import normalize_prefix

# Lädt die .env-Datei aus dem Projektverzeichnis in os.environ.
# override=False: Bereits gesetzte Variablen (z. B. aus docker-compose "environment:")
# haben Vorrang vor der .env – so kann Compose z. B. APP_ENV=production erzwingen.
load_dotenv(override=False)


def _env_bool(name: str, default: bool) -> bool:
    """Liest eine Umgebungsvariable als Wahrheitswert ("1", "true", "yes", "on" = True)."""
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class BaseConfig:
    """Gemeinsame Einstellungen für alle Umgebungen."""

    # --- Allgemein -----------------------------------------------------------------
    # SECRET_KEY signiert u. a. die Passwort-Reset-Tokens (itsdangerous).
    # Kein Fallback-Wert! Fehlt er in Produktion, bricht validate() den Start ab.
    SECRET_KEY = os.getenv("SECRET_KEY")
    DEBUG = False
    TESTING = False

    # Öffentliche Basis-URL der Anwendung, wie der Browser sie sieht (hinter Nginx).
    # Wird für Links in E-Mails verwendet (Passwort-Reset, Einladungen).
    APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8080").rstrip("/")

    # Pfad, unter dem die App erreichbar ist (Server: "/kalender" auf
    # intern.bellmann-engineering.com), lokal leer. APP_BASE_URL enthält ihn bereits.
    # Siehe app/utils/url_prefix.py.
    APP_URL_PREFIX = normalize_prefix(os.getenv("APP_URL_PREFIX"))

    # Geschäftszeitzone. In der DB wird IMMER UTC gespeichert; diese Zone dient nur dazu,
    # Datumsangaben OHNE Zeitzonen-Info (z. B. "2026-09-25T10:00") korrekt als
    # deutsche Ortszeit zu interpretieren. Siehe app/utils/time.py.
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Europe/Berlin")

    # Maximale Größe eines HTTP-Requests (schützt z. B. den CSV-Upload vor Riesendateien).
    # Flask antwortet bei Überschreitung automatisch mit 413.
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 2 * 1024 * 1024))

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

    # --- Datenbank (SQLAlchemy -> psycopg 3 -> PostgreSQL) ---------------------------
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Connection-Pool pro Gunicorn-Prozess. Rechnung (siehe gunicorn.conf.py):
    #   3 Worker x (5 + 2) = max. 21 Verbindungen  <<  100 (PostgreSQL-Standard).
    # Pro Worker laufen 4 Threads -> 4 gleichzeitige Verbindungen passen in pool_size=5.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": int(os.getenv("DB_POOL_SIZE", 5)),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", 2)),
        # Prüft vor jeder Nutzung mit einem leichten "SELECT 1", ob die Verbindung noch lebt
        # (z. B. nach einem Neustart des DB-Containers) – verhindert sporadische 500er.
        "pool_pre_ping": True,
        # Verbindungen nach 30 Minuten erneuern, bevor Firewalls/NAT sie still kappen.
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", 1800)),
    }

    # --- JWT (Flask-JWT-Extended) -----------------------------------------------------
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
    # Tokens liegen in HttpOnly-Cookies -> JavaScript (und damit XSS) kommt nicht heran.
    # "headers" bleibt zusätzlich erlaubt, damit Skripte/Tools die API mit
    # "Authorization: Bearer <token>" nutzen können (dort ist kein CSRF-Risiko).
    JWT_TOKEN_LOCATION = ["cookies", "headers"]
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=int(os.getenv("JWT_ACCESS_MINUTES", 30)))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(hours=int(os.getenv("JWT_REFRESH_HOURS", 8)))
    # Secure=True: Cookie nur über HTTPS. Browser behandeln http://localhost als sicher,
    # für andere Hosts OHNE TLS muss COOKIE_SECURE=0 gesetzt werden (siehe .env.example).
    JWT_COOKIE_SECURE = _env_bool("COOKIE_SECURE", True)
    # Strict: Der Browser schickt die Cookies NIE bei Anfragen von fremden Seiten mit.
    JWT_COOKIE_SAMESITE = "Strict"
    # Double-Submit-CSRF-Schutz: Bei POST/PUT/PATCH/DELETE muss das Frontend den Wert
    # des lesbaren Cookies "csrf_access_token" im Header "X-CSRF-TOKEN" mitschicken.
    JWT_COOKIE_CSRF_PROTECT = True
    # Das Refresh-Cookie wird nur an /api/v1/auth/* gesendet (refresh, logout) ...
    JWT_REFRESH_COOKIE_PATH = "/api/v1/auth"
    # ... das zugehörige CSRF-Cookie muss aber auf jeder Seite für JS lesbar sein.
    JWT_REFRESH_CSRF_COOKIE_PATH = "/"
    # Session-Cookies (ohne Max-Age) würden beim Schließen des Browsers verfallen und
    # mit der Token-Laufzeit kollidieren -> Cookie-Laufzeit = Token-Laufzeit.
    JWT_SESSION_COOKIE = False

    # --- Rate-Limiting (Flask-Limiter) ------------------------------------------------
    # memory:// = Zähler pro Gunicorn-Prozess. Der wirksame, prozessübergreifende Schutz
    # für Login/Passwort-Reset sitzt in Nginx (limit_req, siehe nginx/nginx.conf).
    # Für geteilte Zähler in der App: RATELIMIT_STORAGE_URI=redis://redis:6379/0
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_ENABLED = True
    RATELIMIT_HEADERS_ENABLED = True

    # --- E-Mail / SMTP ------------------------------------------------------------------
    SMTP_SERVER = os.getenv("SMTP_SERVER", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "noreply@bellmann-engineering.com")
    # True: E-Mails werden in einem Hintergrund-Thread versendet, der HTTP-Request
    # wartet also nicht auf den (langsamen) SMTP-Server. In Tests synchron.
    MAIL_ASYNC = True

    # --- Google Calendar -----------------------------------------------------------------
    # OAuth-Client aus der Google Cloud Console ("Webanwendung"). Damit verbindet ein
    # CEO/ADMIN einmalig sein Google-Konto; die App sieht danach alle Kalender, die dieses
    # Konto in Google Kalender sieht (siehe app/services/google_oauth_service.py).
    GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    # Muss EXAKT so in der Google Cloud Console als "Autorisierte Weiterleitungs-URI"
    # eingetragen sein. Standard: <APP_BASE_URL>/api/v1/google/oauth/callback
    GOOGLE_OAUTH_REDIRECT_URI = os.getenv(
        "GOOGLE_OAUTH_REDIRECT_URI", f"{APP_BASE_URL}/api/v1/google/oauth/callback"
    )
    # Wie lange Frei/Belegt-Antworten von Google zwischengespeichert werden (Sekunden).
    # Spart API-Aufrufe, wenn mehrere Personen gleichzeitig den Kalender ansehen.
    GOOGLE_BUSY_CACHE_SECONDS = int(os.getenv("GOOGLE_BUSY_CACHE_SECONDS", 60))

    # --- Single Sign-on über Authelia (Traefik forwardAuth) --------------------------------
    # Auf dem Server steht Traefik mit Authelia vor der App. Nach erfolgreicher Anmeldung
    # bei Authelia setzt Traefik den Header "Remote-Email". Ist AUTHELIA_SSO an, meldet
    # /login den Mitarbeiter mit genau dieser E-Mail-Adresse ohne Passwort an.
    # NUR einschalten, wenn die App ausschließlich über Traefik+Authelia erreichbar ist –
    # sonst könnte jeder den Header selbst mitschicken. Lokal (nginx) bleibt es aus.
    AUTHELIA_SSO = _env_bool("AUTHELIA_SSO", False)
    AUTHELIA_EMAIL_HEADER = os.getenv("AUTHELIA_EMAIL_HEADER", "Remote-Email")
    # Optional: Nach "Abmelden" dorthin weiterleiten (z. B. https://auth.example.com/logout),
    # damit auch die Authelia-Sitzung endet. Leer = zurück zur Login-Seite.
    AUTHELIA_LOGOUT_URL = os.getenv("AUTHELIA_LOGOUT_URL", "")

    # --- Flask-Session (NUR für den Google-Anmeldeablauf) ---------------------------------
    # Die Login-Cookies (JWT) sind SameSite=Strict und werden deshalb bei der Rückkehr von
    # accounts.google.com NICHT mitgeschickt. Den OAuth-"state" (Schutz gegen CSRF beim
    # Anmelden) merken wir uns daher in einer eigenen, signierten Session mit SameSite=Lax:
    # Lax-Cookies sendet der Browser bei einer normalen Weiterleitung (GET) von fremden Seiten.
    SESSION_COOKIE_NAME = "bellmann_oauth"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("COOKIE_SECURE", True)
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=15)

    # --- Passwort-Reset / Einladungen ----------------------------------------------------
    PASSWORD_RESET_MAX_AGE = int(os.getenv("PASSWORD_RESET_MAX_AGE", 30 * 60))
    INVITE_MAX_AGE = int(os.getenv("INVITE_MAX_AGE", 72 * 60 * 60))
    PASSWORD_MIN_LENGTH = 10

    @classmethod
    def validate(cls) -> None:
        """Prüft die Konfiguration vor dem Start. Basisklasse: nur die DB-URL."""
        if not cls.SQLALCHEMY_DATABASE_URI:
            raise RuntimeError(
                "DATABASE_URL ist nicht gesetzt. Bitte in der .env-Datei definieren."
            )


class DevelopmentConfig(BaseConfig):
    """Lokale Entwicklung. DEBUG nur, wenn FLASK_DEBUG=1 explizit gesetzt ist."""

    DEBUG = _env_bool("FLASK_DEBUG", False)
    # Lokal ohne HTTPS: Secure-Cookies standardmäßig aus (per COOKIE_SECURE überschreibbar).
    JWT_COOKIE_SECURE = _env_bool("COOKIE_SECURE", False)
    SESSION_COOKIE_SECURE = JWT_COOKIE_SECURE
    # Damit man lokal ohne .env-Secrets starten kann, werden hier Wegwerf-Schlüssel
    # erzeugt. Sie ändern sich bei jedem Neustart (-> alle Logins ungültig). Gewollt.
    SECRET_KEY = BaseConfig.SECRET_KEY or os.urandom(32).hex()
    JWT_SECRET_KEY = BaseConfig.JWT_SECRET_KEY or os.urandom(32).hex()


class ProductionConfig(BaseConfig):
    """Produktion (Docker + Gunicorn). DEBUG ist unabhängig von der .env immer aus."""

    DEBUG = False

    @classmethod
    def validate(cls) -> None:
        """Fail-fast: Ohne starke Secrets startet die Anwendung in Produktion NICHT."""
        super().validate()
        for name in ("SECRET_KEY", "JWT_SECRET_KEY"):
            value = getattr(cls, name) or ""
            if len(value) < 32:
                raise RuntimeError(
                    f"{name} fehlt oder ist kürzer als 32 Zeichen. "
                    'Erzeugen mit: python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )


class TestingConfig(BaseConfig):
    """pytest: eigene Datenbank (TEST_DATABASE_URL), synchroner Mailversand, kein Limit."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL")
    SECRET_KEY = "test-secret-key-" + "x" * 32
    JWT_SECRET_KEY = "test-jwt-secret-" + "x" * 32
    JWT_COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False
    GOOGLE_OAUTH_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
    GOOGLE_OAUTH_CLIENT_SECRET = "test-client-secret"  # noqa: S105 - nur Testwert
    GOOGLE_OAUTH_REDIRECT_URI = "http://localhost/api/v1/google/oauth/callback"
    GOOGLE_BUSY_CACHE_SECONDS = 0
    RATELIMIT_ENABLED = False
    MAIL_ASYNC = False
    # Kleiner Pool reicht für Tests; NullPool wäre auch möglich.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}


# Zuordnung APP_ENV -> Konfigurationsklasse.
_CONFIGS: dict[str, type[BaseConfig]] = {
    "production": ProductionConfig,
    "development": DevelopmentConfig,
    "testing": TestingConfig,
}


def get_config(env_name: str | None = None) -> type[BaseConfig]:
    """Liefert die Konfigurationsklasse zur Umgebung (Standard: APP_ENV, sonst development).

    Args:
        env_name: Optionaler Name; überschreibt die Umgebungsvariable APP_ENV.

    Raises:
        RuntimeError: Bei unbekanntem Umgebungsnamen (Tippfehler sollen auffallen).
    """
    name = (env_name or os.getenv("APP_ENV", "development")).strip().lower()
    try:
        return _CONFIGS[name]
    except KeyError as exc:
        raise RuntimeError(f"Unbekannte APP_ENV '{name}'. Erlaubt: {', '.join(_CONFIGS)}.") from exc


# Rückwärtskompatibilität: Alter Import "from app.config import Config" funktioniert weiter.
Config = get_config()
