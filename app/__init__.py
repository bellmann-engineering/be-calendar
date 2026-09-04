from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from app.config import Config

db = SQLAlchemy()
jwt = JWTManager()
migrate = Migrate()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)

    # Blueprints registrieren
    from app.routes.auth_routes import auth_bp
    from app.routes.event_routes import event_bp
    from app.routes.ai_routes import ai_bp
    from app.routes.rsvp_routes import rsvp_bp
    from app.routes.skill_routes import skill_bp
    from app.routes.team_routes import team_bp
    from app.routes.notification_routes import notification_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(event_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(rsvp_bp)
    app.register_blueprint(skill_bp)
    app.register_blueprint(team_bp)
    app.register_blueprint(notification_bp)

    @app.route("/health", methods=["GET"])
    def health_check():
        return {"status": "healthy", "service": "bellmann-calendar"}, 200

    return app
