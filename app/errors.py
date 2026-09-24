"""
Globale Fehlerbehandlung: Keine Stacktraces und keine DB-Details an den Client.

Was macht diese Datei?
    Registriert zwei ``errorhandler`` an der Flask-App:

    * ``HTTPException`` (404, 405, 413, 429, ...) -> JSON ``{"error": "..."}`` für
      API-Pfade (``/api/...``); HTML-Seiten behalten die Standard-Fehlerseite.
    * ``Exception`` (alles Unerwartete) -> Stacktrace ins Log (``logger.exception``),
      an den Client nur eine generische Meldung mit Status 500.

    Hintergrund (OWASP A05 "Security Misconfiguration"): Früher gaben Services Texte wie
    ``f"Datenbankfehler: {e}"`` zurück. Damit landeten SQL-Fragmente, Tabellen- und
    Constraint-Namen beim Browser – wertvolle Infos für Angreifer.

Wer benutzt sie?
    ``app/__init__.py::create_app()`` -> ``register_error_handlers(app)``.

Wovon hängt sie ab?
    Flask/Werkzeug. JWT-Fehler behandelt Flask-JWT-Extended selbst (siehe app/security.py);
    Flask wählt immer den spezifischsten Handler, daher gibt es keine Konflikte.
"""

import logging

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)

# Deutsche Standardtexte für die häufigsten HTTP-Fehler.
_MESSAGES = {
    400: "Ungültige Anfrage.",
    401: "Nicht angemeldet.",
    403: "Zugriff verweigert.",
    404: "Ressource nicht gefunden.",
    405: "HTTP-Methode nicht erlaubt.",
    413: "Die hochgeladene Datei ist zu groß.",
    429: "Zu viele Anfragen. Bitte kurz warten und erneut versuchen.",
}


def _wants_json() -> bool:
    """API-Aufrufe bekommen JSON, normale Seitenaufrufe die HTML-Fehlerseite."""
    return request.path.startswith("/api/") or request.is_json


def register_error_handlers(app: Flask) -> None:
    """Registriert die globalen Fehler-Handler an der App."""

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException):
        if not _wants_json():
            return exc
        message = _MESSAGES.get(exc.code or 500, exc.name)
        return jsonify({"error": message}), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected_exception(exc: Exception):
        # Vollständiger Stacktrace NUR ins Server-Log.
        logger.exception("Unbehandelte Ausnahme bei %s %s", request.method, request.path)
        if _wants_json():
            return jsonify({"error": "Interner Serverfehler."}), 500
        return "Interner Serverfehler.", 500
