"""
Strukturiertes Logging für die gesamte Anwendung.

Was macht diese Datei?
    Sie konfiguriert das Python-``logging``-Modul einmalig beim App-Start:
    * Produktion: eine JSON-Zeile pro Log-Eintrag auf stdout. Docker sammelt stdout ein
      (``docker compose logs web``) und Tools wie Loki/ELK können JSON direkt auswerten.
    * Entwicklung/Test: gut lesbares Textformat.

Wer benutzt sie?
    ``app/__init__.py::create_app()`` ruft ``configure_logging(app)`` auf.
    Jedes Modul holt sich danach seinen eigenen Logger mit
    ``logger = logging.getLogger(__name__)`` – statt ``print()``.

Wovon hängt sie ab?
    Nur von der Standardbibliothek (``logging``, ``json``).
"""

import json
import logging
import logging.config
from datetime import datetime, timezone

from flask import Flask


class JsonFormatter(logging.Formatter):
    """Formatiert einen LogRecord als einzeilige JSON-Struktur."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            # Zeitstempel immer in UTC und mit Offset -> eindeutig über Zeitzonen hinweg.
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Bei logger.exception(...) den kompletten Stacktrace mitschreiben – aber NUR ins
        # Log, niemals in die HTTP-Antwort (dafür sorgt app/errors.py).
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(app: Flask) -> None:
    """Richtet Root-Logger, Level und Formatter passend zur Umgebung ein."""
    use_json = not (app.debug or app.testing)
    logging.config.dictConfig(
        {
            "version": 1,
            # Bestehende Logger (z. B. von Gunicorn, SQLAlchemy) nicht abschalten.
            "disable_existing_loggers": False,
            "formatters": {
                "json": {"()": JsonFormatter},
                "text": {"format": "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"},
            },
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "json" if use_json else "text",
                }
            },
            "root": {"level": app.config.get("LOG_LEVEL", "INFO"), "handlers": ["stdout"]},
            "loggers": {
                # SQL-Statements nur bei Bedarf (LOG_LEVEL=DEBUG + hier anpassen).
                "sqlalchemy.engine": {"level": "WARNING"},
                # googleapiclient ist sehr gesprächig auf INFO.
                "googleapiclient.discovery_cache": {"level": "ERROR"},
            },
        }
    )
