import os
from dotenv import load_dotenv

# Laden der .env-Datei aus dem Hauptverzeichnis
load_dotenv()


class Config:
    """Zentrale Konfigurationsklasse für die Flask-Anwendung."""

    # Allgemeine Flask-Einstellungen
    SECRET_KEY = os.getenv("SECRET_KEY", "default_fallback_secret_key")
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

    # Datenbank-Einstellungen (SQLAlchemy)
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # JWT Sicherheits-Einstellungen
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "default_jwt_secret_key")

    # KI / Ollama Einstellungen
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")

    # E-Mail / SMTP Einstellungen
    SMTP_SERVER = os.getenv("SMTP_SERVER", "localhost")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv(
        "MAIL_DEFAULT_SENDER", "noreply@bellmann-engineering.com"
    )
