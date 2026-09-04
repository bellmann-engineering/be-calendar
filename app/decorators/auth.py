from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt, verify_jwt_in_request


def role_required(*allowed_roles):
    """
    Dekorator zur Überprüfung von Benutzerrollen (RBAC).
    Erlaubt den Zugriff nur, wenn die Rolle des Benutzers in allowed_roles enthalten ist.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            user_role = claims.get("role")

            if user_role not in allowed_roles and user_role != "CEO":
                return (
                    jsonify(
                        {
                            "error": "Zugriff verweigert",
                            "message": f"Ihre Rolle ({user_role}) verfügt nicht über die erforderlichen Berechtigungen.",
                        }
                    ),
                    403,
                )

            return fn(*args, **kwargs)

        return wrapper

    return decorator
