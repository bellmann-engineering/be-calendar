from flask import Blueprint, render_template, redirect, url_for
from app.models import User

calendar_bp = Blueprint("calendar_ui", __name__)


@calendar_bp.route("/")
def index():
    return redirect(url_for("calendar_ui.dashboard"))


@calendar_bp.route("/login")
def login():
    return render_template("login.html")


@calendar_bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@calendar_bp.route("/customers")
def customers():
    return render_template("customers.html")


@calendar_bp.route("/compare")
def compare():
    # Rollenfilter entfernt. Lädt nun ALLE aktiven Benutzer.
    all_users = User.query.filter_by(is_active=True).all()
    return render_template("compare.html", trainers=all_users)


@calendar_bp.route("/logs")
def logs():
    return render_template("logs.html")


@calendar_bp.route("/members")
def members():
    return render_template("members.html")
