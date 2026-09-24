"""
WSGI-Einstiegspunkt für den Produktionsserver.

Wer benutzt diese Datei?
    * Gunicorn im Docker-Container: ``gunicorn -c gunicorn.conf.py wsgi:app``
      ("wsgi:app" = Modul wsgi, Variable app).
    * Flask-CLI / Alembic im Container (FLASK_APP=wsgi.py), z. B. ``flask db upgrade``.

Die Umgebung (production/development) bestimmt die Variable APP_ENV, die in
docker-compose.yml fest auf "production" gesetzt ist.
"""

from app import create_app

app = create_app()
