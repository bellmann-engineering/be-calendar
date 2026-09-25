"""
Sicherheits-Header für JEDE Antwort der App.

Warum in der App und nicht im Proxy?
    Lokal steht nginx vor der App, auf dem Server Traefik (+ Authelia). Setzt die App die
    Header selbst, gelten sie hinter beiden Proxys gleich – ohne doppelte Pflege.
    (Früher standen sie in nginx/nginx.conf und fehlten hinter Traefik.)

Wer ruft das auf?
    ``app/__init__.py::create_app()`` -> ``register_security_headers(app)``.
"""

from flask import Flask, Response, request

# Content-Security-Policy (strikt): ALLES kommt von der eigenen Domain.
#   script-src 'self'  -> kein Inline-JS, keine onclick-Attribute, kein CDN. Selbst
#                         wenn Angreifer HTML einschleusen könnten, würde der Browser
#                         darin enthaltene Skripte nicht ausführen.
#   style-src  'self' + Hash des LEEREN Strings (sha256-47DEQ...): FullCalendar legt
#                         ein leeres <style>-Element an und füllt es danach über die
#                         CSSOM-API (sheet.insertRule), die nicht unter die CSP fällt.
#                         Der Hash erlaubt ausschließlich leere Inline-Styles – kein
#                         'unsafe-inline', eingeschleustes CSS wird weiter blockiert.
#   font-src   data:   -> FullCalendar bettet seine Pfeil-Icons als Daten-URL-Schrift ein.
#   img-src    data:   -> Auswahlpfeil der Selectboxen (SVG als Daten-URL im CSS).
#   img-src    blob:   -> Vorschau eines gewählten Kunden-Logos vor dem Hochladen
#                         (URL.createObjectURL, nur im eigenen Browser erzeugt).
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU='; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests"
)

_STATIC_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    # Clickjacking-Schutz: Seite darf nicht in fremde iframes eingebettet werden.
    "X-Frame-Options": "DENY",
    # Browser soll Content-Types nicht "erraten" (MIME-Sniffing).
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}

# HSTS ("Browser, nutze für diese Domain NUR noch HTTPS") nur für echte Hostnamen.
# Für localhost wäre HSTS schädlich: Der Browser würde sich das für JEDEN Port auf
# localhost merken und auch andere lokale Entwicklungsserver auf HTTPS zwingen.
_NO_HSTS_HOSTS = {"localhost", "127.0.0.1"}


def register_security_headers(app: Flask) -> None:
    """Hängt die Sicherheits-Header per ``after_request`` an jede Antwort."""

    @app.after_request
    def _add_security_headers(response: Response) -> Response:
        for name, value in _STATIC_HEADERS.items():
            response.headers.setdefault(name, value)
        # request.is_secure/host stimmen dank ProxyFix (X-Forwarded-Proto/-Host).
        if request.is_secure and request.host.split(":")[0] not in _NO_HSTS_HOSTS:
            # Ohne includeSubDomains: Der Host (intern.bellmann-engineering.com) gehört
            # nicht der App allein, über Subdomains entscheidet sie nicht.
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response
