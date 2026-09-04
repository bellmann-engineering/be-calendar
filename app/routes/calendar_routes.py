from flask import Blueprint, render_template, redirect, url_for

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
