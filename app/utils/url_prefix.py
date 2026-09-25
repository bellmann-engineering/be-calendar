"""
Betrieb unter einem URL-Präfix, z. B. https://intern.bellmann-engineering.com/kalender/...

Warum?
    Auf dem Server schützt Authelia den Host intern.bellmann-engineering.com; die App
    läuft dort unter einem Pfad (APP_URL_PREFIX, z. B. "/kalender") neben anderen Diensten.
    Lokal (nginx) ist der Präfix leer und alles bleibt wie gehabt.

Wie?
    * ``PrefixMiddleware`` (WSGI) setzt SCRIPT_NAME auf den Präfix und entfernt ihn aus
      PATH_INFO. Die Routen bleiben dadurch unverändert (/login, /api/v1/...), und
      ``url_for()`` / ``request.script_root`` liefern automatisch "/kalender/...".
      Traefik braucht deshalb KEIN StripPrefix – Authelia sieht den vollen Pfad.
      Anfragen ohne Präfix (Docker-HEALTHCHECK auf /health) funktionieren weiterhin.
    * ``apply_prefix_to_cookie_paths()`` beschränkt alle Cookies auf den Präfix: Andere
      Dienste auf demselben Host bekommen die Sitzungs-Cookies nie zu sehen.
    * Das Frontend liest den Präfix aus <meta name="app-base"> (base.html) und setzt
      ihn vor alle Pfade (app.js::appUrl / apiFetch).

Wer ruft das auf?
    ``app/__init__.py::create_app()``.
"""

from flask import Flask


def normalize_prefix(value: str | None) -> str:
    """Einheitliche Form: kalender/ -> /kalender; leer oder / -> "" (kein Präfix)."""
    value = (value or "").strip().strip("/")
    return f"/{value}" if value else ""


class PrefixMiddleware:
    """WSGI-Middleware: verschiebt den Präfix von PATH_INFO nach SCRIPT_NAME."""

    def __init__(self, wsgi_app, prefix: str):
        self.wsgi_app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path == self.prefix or path.startswith(self.prefix + "/"):
            environ["PATH_INFO"] = path[len(self.prefix) :] or "/"
        environ["SCRIPT_NAME"] = self.prefix
        return self.wsgi_app(environ, start_response)


def apply_prefix_to_cookie_paths(app: Flask, prefix: str) -> None:
    """Setzt die Pfade aller Cookies (JWT, CSRF, OAuth-Session) unter den Präfix."""
    app.config.update(
        JWT_ACCESS_COOKIE_PATH=prefix,
        JWT_ACCESS_CSRF_COOKIE_PATH=prefix,
        JWT_REFRESH_COOKIE_PATH=prefix + "/api/v1/auth",
        JWT_REFRESH_CSRF_COOKIE_PATH=prefix,
        SESSION_COOKIE_PATH=prefix,
    )
