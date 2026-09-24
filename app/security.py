"""
JWT-Integration: Wie wird aus einem Cookie/Token ein eingeloggter Benutzer?

Was macht diese Datei?
    Sie registriert die Callbacks von Flask-JWT-Extended:

    1. ``user_identity_loader``  – was beim Login ins Token geschrieben wird ("sub" = User-ID).
    2. ``user_lookup_loader``    – lädt bei JEDEM geschützten Request den User frisch aus
       der Datenbank (inkl. Rolle, per JOIN in einer Query). Danach steht er in den Routen
       als ``flask_jwt_extended.current_user`` zur Verfügung.
       Vorteil: Wird ein Benutzer deaktiviert oder herabgestuft, wirkt das SOFORT –
       nicht erst, wenn sein Token abläuft. Eine Token-Blocklist ist dadurch unnötig.
    3. Fehler-Callbacks – einheitliche JSON-Antworten ``{"error": "..."}`` mit Status 401
       statt der englischen Standardtexte bzw. 422.

Wer benutzt sie?
    ``app/__init__.py::create_app()`` -> ``register_jwt_callbacks(jwt)``.
    Die Routen nutzen danach ``@jwt_required()`` und ``current_user``.

Wovon hängt sie ab?
    Flask-JWT-Extended, SQLAlchemy (``app.db``) und das Model ``User``.
"""

import logging

from flask import jsonify
from flask_jwt_extended import JWTManager
from sqlalchemy.orm import joinedload

logger = logging.getLogger(__name__)


def register_jwt_callbacks(jwt: JWTManager) -> None:
    """Hängt alle JWT-Callbacks an die übergebene JWTManager-Instanz."""
    # Import hier drin, um einen Zirkelimport (app -> models -> app) zu vermeiden.
    from app import db
    from app.models import User

    @jwt.user_identity_loader
    def user_identity(identity: object) -> str:
        """Schreibt die User-ID als String in den Claim "sub" (JWT-Standard verlangt String)."""
        if isinstance(identity, User):
            return str(identity.id)
        return str(identity)

    @jwt.user_lookup_loader
    def load_user(_jwt_header: dict, jwt_data: dict) -> User | None:
        """Lädt den Benutzer zum Token. None -> Flask-JWT-Extended antwortet mit 401.

        ``joinedload(User.role)`` holt die Rolle im selben SELECT (kein N+1), denn fast
        jede Route prüft danach ``current_user.role.name``.
        """
        try:
            user_id = int(jwt_data["sub"])
        except (KeyError, TypeError, ValueError):
            return None
        user = db.session.get(User, user_id, options=[joinedload(User.role)])
        if user is None or not user.is_active:
            return None
        return user

    @jwt.user_lookup_error_loader
    def user_lookup_error(_jwt_header: dict, _jwt_data: dict):
        return jsonify({"error": "Benutzer nicht gefunden oder deaktiviert."}), 401

    @jwt.expired_token_loader
    def expired_token(_jwt_header: dict, _jwt_data: dict):
        # Das Frontend (app.js::apiFetch) reagiert auf 401 mit einem Refresh-Versuch.
        return jsonify({"error": "Sitzung abgelaufen. Bitte erneut anmelden."}), 401

    @jwt.invalid_token_loader
    def invalid_token(reason: str):
        logger.info("Ungültiges JWT abgewiesen: %s", reason)
        return jsonify({"error": "Ungültiges Sitzungs-Token."}), 401

    @jwt.unauthorized_loader
    def missing_token(reason: str):
        # Wird auch bei fehlendem/falschem CSRF-Header aufgerufen.
        return jsonify({"error": "Nicht angemeldet oder CSRF-Token fehlt."}), 401

    @jwt.revoked_token_loader
    def revoked_token(_jwt_header: dict, _jwt_data: dict):
        return jsonify({"error": "Token wurde widerrufen."}), 401
