"""
Lokaler Entwicklungsserver (NICHT für Produktion).

Start:
    python run.py            -> http://127.0.0.1:5000

Sicherheit:
    * Der Werkzeug-Debugger (interaktive Python-Konsole im Browser!) ist nur aktiv, wenn
      FLASK_DEBUG=1 gesetzt ist. Früher war debug=True fest einprogrammiert.
    * Standardmäßig wird nur an 127.0.0.1 gebunden – also nur vom eigenen Rechner
      erreichbar. Mit DEV_HOST=0.0.0.0 bewusst im Netzwerk freigeben.
    * In Docker läuft stattdessen Gunicorn (siehe wsgi.py, gunicorn.conf.py).
"""

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.getenv("DEV_HOST", "127.0.0.1"),
        port=int(os.getenv("DEV_PORT", "5000")),
        debug=app.debug,  # kommt aus der Config: nur bei FLASK_DEBUG=1 in development
    )
