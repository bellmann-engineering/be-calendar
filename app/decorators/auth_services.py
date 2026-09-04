from werkzeug.security import check_password_hash
from flask_jwt_extended import create_access_token
from app.models import User


class AuthService:
    """Service-Schicht für Authentifizierung und Token-Generierung."""

    @staticmethod
    def authenticate_user(email, password):
        user = User.query.filter_by(email=email, is_active=True).first()
        if not user or not check_password_hash(user.password_hash, password):
            return None

        # Zuweisung von Custom Claims für RBAC im JWT
        additional_claims = {
            "role": user.role.name,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }

        # Generierung des Access-Tokens (Gültigkeit in Config steuerbar)
        access_token = create_access_token(
            identity=str(user.id), additional_claims=additional_claims
        )

        return {
            "access_token": access_token,
            "user": {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "role": user.role.name,
            },
        }
