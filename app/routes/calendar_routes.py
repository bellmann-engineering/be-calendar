"""
HTML-Seiten (Server-Side-Rendering mit Jinja2) – nur das "Gerüst" der Oberfläche.

Wichtig zum Verständnis:
    Diese Routen liefern nur leere Seiten-Hüllen aus. ALLE Daten lädt das JavaScript im
    Browser anschließend über die JSON-API (/api/v1/...), die per JWT-Cookie geschützt
    ist. Deshalb stehen hier bewusst keine Datenbankabfragen – früher lieferte /compare
    ohne jede Anmeldung die Namen aller Mitarbeiter aus.

    Ist man nicht angemeldet, merkt das ``app.js`` (401 bei /api/v1/auth/me) und leitet
    auf /login um.

Templates: ``app/templates/*.html`` (erben alle von base.html).
"""

from flask import Blueprint, redirect, render_template, url_for

calendar_bp = Blueprint("calendar_ui", __name__)


@calendar_bp.route("/")
def index():
    return redirect(url_for("calendar_ui.dashboard"))


@calendar_bp.route("/login")
def login():
    return render_template("login.html")


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
