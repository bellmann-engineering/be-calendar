"""
HTML-Seiten (Server-Side-Rendering mit Jinja2) – nur das "Gerüst" der Oberfläche.

Wichtig zum Verständnis:
    Diese Routen liefern nur leere Seiten-Hüllen aus. ALLE Daten lädt das JavaScript im
    Browser anschließend über die JSON-API (/api/v1/...), die per JWT-Cookie geschützt
    ist. Deshalb stehen hier bewusst keine Datenbankabfragen – früher lieferte /compare
    ohne jede Anmeldung die Namen aller Mitarbeiter aus.

    Ist man nicht angemeldet, merkt das ``app.js`` (401 bei /api/v1/auth/me) und leitet
    auf /login?next=<Seite> um.

Single Sign-on (Authelia):
    Hat Authelia den Besucher schon angemeldet (Header Remote-Email, AUTHELIA_SSO=1) und
    gibt es einen aktiven Mitarbeiter mit dieser E-Mail, überspringt /login die Maske:
    Cookies setzen und direkt weiter zu ``next`` (sonst /dashboard). Nach dem Abmelden
    (``?abgemeldet=1``) bleibt die Maske stehen, sonst wäre man sofort wieder drin.

Templates: ``app/templates/*.html`` (erben alle von base.html).
"""

from flask import Blueprint, redirect, render_template, request, url_for

from app.security import proxy_auth_email, set_session_cookies
from app.services.auth_service import AuthService

calendar_bp = Blueprint("calendar_ui", __name__)


def _safe_next(target: str | None) -> str:
    """Nur Pfade dieser App als Ziel – kein Open Redirect auf fremde Seiten.

    ``next`` ist ein Pfad OHNE URL-Präfix (app.js::redirectToLogin), der Präfix
    (request.script_root, z. B. "/kalender") kommt hier davor.
    """
    if (
        target
        and target.startswith("/")
        and not target.startswith(("//", "/\\"))
        and not target.startswith("/login")
    ):
        return request.script_root + target
    return url_for("calendar_ui.dashboard")


@calendar_bp.route("/")
def index():
    # Mit Authelia direkt über /login: spart den Umweg Dashboard -> 401 -> /login.
    if proxy_auth_email():
        return redirect(url_for("calendar_ui.login"))
    return redirect(url_for("calendar_ui.dashboard"))


@calendar_bp.route("/login")
def login():
    sso_email = proxy_auth_email()
    sso_user = AuthService.authenticate_proxy_user(sso_email) if sso_email else None
    if sso_user is not None and not request.args.get("abgemeldet"):
        response = redirect(_safe_next(request.args.get("next")))
        return set_session_cookies(response, sso_user)
    # Sonst normale Maske – mit Hinweis, falls Authelia jemanden kennt:
    #   sso_user gesetzt  -> gerade abgemeldet, "Weiter als ..." anbieten
    #   sso_user fehlt    -> zu dieser E-Mail gibt es keinen (aktiven) Mitarbeiter
    return render_template("login.html", sso_email=sso_email, sso_known=sso_user is not None)


@calendar_bp.route("/reset-password")
def reset_password():
    """Öffentliche Seite zum Setzen eines neuen Passworts (Token steht in der URL)."""
    return render_template("reset_password.html")


@calendar_bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@calendar_bp.route("/customers")
def customers():
    return render_template("customers.html")


@calendar_bp.route("/compare")
def compare():
    # Mitarbeiterliste lädt compare.html selbst über GET /api/v1/auth (geschützt).
    return render_template("compare.html")


@calendar_bp.route("/logs")
def logs():
    return render_template("logs.html")


@calendar_bp.route("/members")
def members():
    return render_template("members.html")
