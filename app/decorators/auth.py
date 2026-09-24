"""
Dekorator ``@role_required(...)`` – rollenbasierte Zugriffskontrolle (RBAC) für Routen.

Beispiel:
    @event_bp.route("", methods=["POST"])
    @jwt_required()
    @role_required("CEO", "ADMIN", "TEAM_LEADER")
    def create_event(): ...

Was passiert?
    1. ``verify_jwt_in_request()`` prüft Cookie/Header, Signatur, Ablauf und – bei
       schreibenden Methoden – den CSRF-Header.
    2. Flask-JWT-Extended ruft dabei ``app/security.py::load_user`` auf, das den User
       FRISCH aus der Datenbank lädt (inkl. Rolle).
    3. Wir vergleichen ``current_user.role.name`` mit den erlaubten Rollen.
       Früher wurde die Rolle aus dem Token-Claim gelesen – ein herabgestufter Admin
       behielt seine Rechte dann bis zum Ablauf des Tokens. Jetzt wirkt es sofort.

Der CEO darf immer alles (implizit erlaubt).
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import jsonify
from flask_jwt_extended import current_user, verify_jwt_in_request

from app.models import RoleEnum


def role_required(*allowed_roles: str) -> Callable:
    """Erlaubt den Zugriff nur, wenn die Rolle des Benutzers in ``allowed_roles`` steht."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            verify_jwt_in_request()
            user_role = current_user.role.name

            if user_role not in allowed_roles and user_role != RoleEnum.CEO.value:
                return (
                    jsonify(
                        {
                            "error": "Zugriff verweigert",
                            "message": (
                                f"Ihre Rolle ({user_role}) verfügt nicht über die "
                                "erforderlichen Berechtigungen."
                            ),
                        }
                    ),
                    403,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
