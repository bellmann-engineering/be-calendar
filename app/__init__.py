from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from app.config import Config

limiter = Limiter(
    key_func=get_remote_address, default_limits=["200 per day", "50 per hour"]
)

db = SQLAlchemy()
jwt = JWTManager()
migrate = Migrate()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    # Blueprints registrieren
    from app.routes.auth_routes import auth_bp
    from app.routes.event_routes import event_bp
    from app.routes.rsvp_routes import rsvp_bp
    from app.routes.skill_routes import skill_bp
    from app.routes.team_routes import team_bp
    from app.routes.notification_routes import notification_bp
    from app.routes.calendar_routes import calendar_bp
    from app.routes.customer_routes import customer_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(event_bp)
    app.register_blueprint(rsvp_bp)
    app.register_blueprint(skill_bp)
    app.register_blueprint(team_bp)
    app.register_blueprint(notification_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(customer_bp)

    with app.app_context():
        pass  # db.create_all() entfernt -> wird nun über Alembic (flask db upgrade) gesteuert

    @app.route("/health", methods=["GET"])
    def health_check():
        return {"status": "healthy", "service": "bellmann-calendar"}, 200

    return app
