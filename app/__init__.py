"""
Application Factory der Kalender-Anwendung der Bellmann Engineering GmbH.

Was macht diese Datei?
    1. Sie erzeugt die globalen Flask-Erweiterungen (``db``, ``jwt``, ``migrate``,
       ``limiter``). Andere Module importieren sie mit ``from app import db`` usw.
    2. ``create_app()`` baut daraus die eigentliche Flask-App zusammen:
       Konfiguration laden -> Logging -> Erweiterungen -> Proxy-Fix -> JWT-Callbacks ->
       Fehler-Handler -> Blueprints (Routen) registrieren.

Wer ruft sie auf?
    * ``wsgi.py``   – Gunicorn in Docker (Produktion)
    * ``run.py``    – ``python run.py`` / ``flask run`` lokal
    * ``seed.py``, ``seed_dev.py`` – Initialdaten
    * ``tests/conftest.py`` – pytest
    * Flask-Migrate/Alembic (``flask db upgrade``) über ``FLASK_APP``

Womit spricht die App?
    * PostgreSQL über SQLAlchemy + psycopg 3 (``DATABASE_URL``)
    * SMTP-Server (E-Mails), Google Calendar API (optional)
    * Der Browser spricht NICHT direkt mit ihr, sondern über einen Reverse Proxy:
      lokal nginx, auf dem Server Traefik (+ Authelia).

Wichtig: Das Datenbankschema wird ausschließlich über Alembic-Migrationen verwaltet
(``flask db upgrade``). ``db.create_all()`` wird bewusst NIE aufgerufen.
"""

import logging

from flask import Flask
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import BaseConfig, get_config

# --- Globale Erweiterungen ----------------------------------------------------------------
# Sie werden hier OHNE App erzeugt und erst in create_app() mit init_app() gebunden
# ("Application Factory Pattern"). So können Tests mehrere Apps erzeugen.

# Rate-Limiter: Schlüssel ist die Client-IP. Die echte IP kommt dank ProxyFix (unten)
# aus dem Header X-Forwarded-For, den Nginx setzt – sonst hätten alle Benutzer die IP
# des Nginx-Containers und teilten sich ein einziges Limit.
# Bewusst KEINE default_limits: Viele Mitarbeiter sitzen hinter derselben Büro-IP (NAT);
# ein globales Limit würde sie gegenseitig aussperren. Limits stehen gezielt an
# sensiblen Endpunkten (Login, Passwort-Reset, CSV-Import).
limiter = Limiter(key_func=get_remote_address)

db = SQLAlchemy()
jwt = JWTManager()
migrate = Migrate()

logger = logging.getLogger(__name__)


def create_app(config_class: type[BaseConfig] | None = None) -> Flask:
    """Erzeugt und konfiguriert eine Flask-App-Instanz.

    Args:
        config_class: Optional eine Konfigurationsklasse (z. B. ``TestingConfig``).
            Ohne Angabe entscheidet die Umgebungsvariable ``APP_ENV``.

    Returns:
        Die fertig konfigurierte Flask-Anwendung.
    """
    config_class = config_class or get_config()
    # Fail-fast: fehlende DB-URL oder schwache Secrets in Produktion -> Start abbrechen.
    config_class.validate()

    app = Flask(__name__)
    app.config.from_object(config_class)

    # Logging so früh wie möglich, damit auch Startfehler strukturiert geloggt werden.
    from app.logging_config import configure_logging

    configure_logging(app)

    # --- Erweiterungen an diese App binden -------------------------------------------------
    db.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    # ProxyFix: Vertraut GENAU EINEM vorgeschalteten Proxy (nginx bzw. Traefik) und übernimmt
    # dessen X-Forwarded-For/-Proto/-Host. Dadurch stimmen request.remote_addr (Rate-Limit,
    # Logs) und request.scheme (https-Erkennung). Mehr als 1 wäre ein Sicherheitsrisiko:
    # Clients könnten sich per gefälschtem Header eine beliebige IP geben.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Betrieb unter einem Pfad (z. B. /kalender hinter Traefik+Authelia), lokal leer.
    from app.utils.url_prefix import PrefixMiddleware, apply_prefix_to_cookie_paths

    prefix = app.config["APP_URL_PREFIX"]
    if prefix:
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix)
        apply_prefix_to_cookie_paths(app, prefix)

    # --- JWT-Callbacks (User-Lookup, Fehlermeldungen) und globale Fehler-Handler ---------
    from app.errors import register_error_handlers
    from app.security import register_jwt_callbacks

    register_jwt_callbacks(jwt)
    register_error_handlers(app)

    # Modul importieren = SQLAlchemy-Events "after_commit"/"rollback" registrieren
    # (Mails & Google-Aufrufe erst NACH erfolgreichem Commit, siehe utils/transaction.py).
    # Achtung: NICHT "import app.utils.transaction" schreiben – das würde die lokale
    # Variable "app" (die Flask-Instanz) mit dem Paket "app" überschreiben.
    # --- Blueprints (Routen-Gruppen) registrieren ------------------------------------------
    from app.routes.auth_routes import auth_bp
    from app.routes.calendar_routes import calendar_bp
    from app.routes.customer_routes import customer_bp
    from app.routes.event_routes import event_bp
    from app.routes.google_routes import google_bp
    from app.routes.notification_routes import notification_bp
    from app.routes.team_routes import team_bp
    from app.utils import transaction as _transaction  # noqa: F401

    app.register_blueprint(auth_bp)  # /api/v1/auth/...
    app.register_blueprint(event_bp)  # /api/v1/events/...
    app.register_blueprint(team_bp)  # /api/v1/teams/...
    app.register_blueprint(notification_bp)  # /api/v1/notifications/...
    app.register_blueprint(calendar_bp)  # HTML-Seiten: /, /login, /dashboard, ...
    app.register_blueprint(customer_bp)  # /api/v1/customers/...
    app.register_blueprint(google_bp)  # /api/v1/google/... (Google-Kalender-Anbindung)

    # asset_url() für die Templates (Cache-Busting) + Cache-Header für /static/...
    from app.utils.assets import register_asset_helpers

    register_asset_helpers(app)

    # CSP, X-Frame-Options, HSTS & Co. – gleich hinter nginx (lokal) und Traefik (Server).
    from app.utils.security_headers import register_security_headers

    register_security_headers(app)

    @app.route("/health", methods=["GET"])
    @limiter.exempt
    def health_check():
        """Liveness/Readiness-Check für Docker-HEALTHCHECK und Nginx.

        Prüft zusätzlich die Datenbankverbindung: Ist PostgreSQL weg, meldet der
        Container "unhealthy" statt fröhlich 200 zu liefern.
        """
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 - jeder DB-Fehler bedeutet "nicht bereit"
            logger.exception("Health-Check: Datenbank nicht erreichbar")
            return {"status": "unhealthy", "service": "bellmann-calendar"}, 503
        return {"status": "healthy", "service": "bellmann-calendar"}, 200

    return app
