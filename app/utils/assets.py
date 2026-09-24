"""
Statische Assets: Cache-Busting-URLs und passende Cache-Header.

Was macht diese Datei?
    1. ``asset_url("dist/app.css")`` (in allen Templates verfügbar) liefert
       ``/static/dist/app.css?v=<8 Zeichen des SHA-256 der Datei>``.
       Ändert sich der Inhalt (neues Deployment), ändert sich die URL – der Browser
       lädt die neue Datei sofort, ohne dass jemand Strg+F5 drücken muss.
    2. Ein ``after_request``-Hook setzt für ``/static/...``:
         * mit ``?v=...``  -> ``Cache-Control: public, max-age=31536000, immutable``
           (1 Jahr, der Browser fragt gar nicht mehr nach – die URL ist ja eindeutig)
         * ohne ``?v=...`` -> ``Cache-Control: no-cache`` (immer kurz beim Server
           nachfragen; dank ETag meist nur eine 304-Antwort ohne Inhalt)

Wer benutzt sie?
    ``app/__init__.py::create_app()`` ruft ``register_asset_helpers(app)`` auf.
    Die Templates (``app/templates/base.html`` u. a.) rufen ``asset_url()`` auf.

Wovon hängt sie ab?
    Von den Dateien unter ``app/static/``. ``app/static/dist/`` entsteht erst durch den
    Frontend-Build (``npm ci && npm run build`` bzw. die Node-Stufe im Dockerfile).
    Fehlt eine Datei (z. B. in den Tests ohne Build), wird die URL ohne Version
    zurückgegeben statt einen Fehler zu werfen.

Warum Hash statt Versionsnummer?
    Der Hash ergibt sich automatisch aus dem Inhalt – niemand muss daran denken,
    eine Versionsnummer hochzuzählen.
"""

import hashlib
from pathlib import Path

from flask import Flask, Response, request, url_for

# Ein Jahr in Sekunden – Obergrenze, die Browser für "max-age" sinnvoll beachten.
IMMUTABLE_MAX_AGE = 31_536_000


def _file_hash(path: Path) -> str | None:
    """Kurzer SHA-256-Fingerabdruck einer Datei oder None, wenn sie fehlt."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    except OSError:
        return None


def register_asset_helpers(app: Flask) -> None:
    """Registriert ``asset_url`` für Jinja und den Cache-Header-Hook."""
    static_root = Path(app.static_folder or "")
    # Zwischenspeicher: Pfad -> Hash. Im Container ändern sich die Dateien zur Laufzeit
    # nie (neues Image = neuer Prozess), daher genügt einmal rechnen pro Datei.
    # Im Debug-Modus (lokales "python run.py" + "npm run watch:css") wird dagegen bei
    # jedem Aufruf neu gerechnet, damit CSS-Änderungen sofort sichtbar sind.
    cache: dict[str, str | None] = {}

    def asset_url(filename: str) -> str:
        """URL einer statischen Datei inkl. Inhalts-Hash als ``?v=``-Parameter."""
        if app.debug or filename not in cache:
            cache[filename] = _file_hash(static_root / filename)
        version = cache[filename]
        if version is None:
            return url_for("static", filename=filename)
        return url_for("static", filename=filename, v=version)

    app.jinja_env.globals["asset_url"] = asset_url

    @app.after_request
    def _static_cache_headers(response: Response) -> Response:
        """Setzt die Cache-Strategie für statische Dateien (siehe Modul-Docstring)."""
        if request.path.startswith("/static/") and response.status_code in (200, 304):
            if request.args.get("v"):
                response.headers["Cache-Control"] = (
                    f"public, max-age={IMMUTABLE_MAX_AGE}, immutable"
                )
            else:
                response.headers["Cache-Control"] = "no-cache"
        return response
