from app import create_app, db
from app.models import User, Role
from werkzeug.security import generate_password_hash

app = create_app()
with app.app_context():
    role = Role.query.filter_by(name="TRAINER").first()
    email = "trainer@bellmann-engineering.com"
    if not User.query.filter_by(email=email).first():
        db.session.add(
            User(
                email=email,
                password_hash=generate_password_hash("trainer123"),
                first_name="Max",
                last_name="Mustertrainer",
                role_id=role.id,
                is_active=True,
            )
        )
        db.session.commit()
