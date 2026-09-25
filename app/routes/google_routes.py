"""
HTTP-Endpunkte der Google-Kalender-Anbindung (/api/v1/google/...).

    GET  /status             Verbindungsstatus für die Mitarbeiter-Seite        (CEO, ADMIN)
    POST /oauth/start        liefert die Google-Anmelde-URL                      (CEO, ADMIN)
    GET  /oauth/callback     Rückkehr von Google -> Weiterleitung auf /members   (öffentlich*)
    POST /disconnect         Verbindung trennen + Token bei Google widerrufen    (CEO, ADMIN)
    GET  /calendars          alle Kalender des verbundenen Kontos                (CEO, ADMIN)
    POST /calendars/check    "Verbindung prüfen" für eine Kalender-ID            (CEO, ADMIN)
    GET  /events             Termine aus den Google-Kalendern der Mitarbeiter    (angemeldet)

* Der Callback kann kein Login-Cookie prüfen: Die JWT-Cookies sind SameSite=Strict und
  werden bei der Weiterleitung von google.com nicht mitgeschickt. Geschützt ist er über den
  zufälligen "state" in der signierten Session (siehe google_oauth_service.py).

Wer ruft sie auf?  app/static/js/pages/members.js, compare.js, dashboard.js
Wovon hängt die Datei ab?  GoogleOAuthService, GoogleCalendarService, @role_required
"""

from datetime import timedelta

from flask import Blueprint, jsonify, redirect, request, url_for
from flask_jwt_extended import current_user, jwt_required

from app import db
from app.decorators.auth import role_required
from app.models import Event, RoleEnum, User
from app.services.calendar_service import GoogleApiFehler, GoogleCalendarService
from app.services.customer_service import CustomerTagger
from app.services.google_oauth_service import GoogleOAuthService
from app.utils.time import parse_iso_datetime

google_bp = Blueprint("google", __name__, url_prefix="/api/v1/google")

# Größter erlaubter Zeitraum für /events (schützt das Google-Kontingent).
_MAX_ZEITRAUM = timedelta(days=62)


@google_bp.route("/status", methods=["GET"])
@jwt_required()
@role_required("CEO", "ADMIN")
def status():
    return jsonify(GoogleOAuthService.status()), 200


@google_bp.route("/oauth/start", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN")
def oauth_start():
    """Die Oberfläche navigiert anschließend selbst zu dieser URL (window.location)."""
    url, fehler = GoogleOAuthService.start(current_user)
    if fehler:
        return jsonify({"error": fehler}), 400
    return jsonify({"authorization_url": url}), 200


@google_bp.route("/oauth/callback", methods=["GET"])
def oauth_callback():
    """Rückkehr von Google: Ergebnis wird als Parameter an die Mitarbeiter-Seite gegeben."""
    erfolg, meldung = GoogleOAuthService.callback(request.args)
    if erfolg:
        return redirect(url_for("calendar_ui.members", google="verbunden"))
    return redirect(url_for("calendar_ui.members", google="fehler", grund=meldung))


@google_bp.route("/disconnect", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN")
def disconnect():
    GoogleOAuthService.trennen(current_user)
    return jsonify({"message": "Google-Verbindung getrennt."}), 200


@google_bp.route("/calendars", methods=["GET"])
@jwt_required()
@role_required("CEO", "ADMIN")
def calendars():
    """Kalender zur Zuordnung an Mitarbeiter (nur mit OAuth-Verbindung sinnvoll)."""
    if GoogleOAuthService.aktuelle_verbindung() is None:
        return jsonify({"error": "Kein Google-Konto verbunden."}), 409
    try:
        return jsonify({"calendars": GoogleCalendarService().list_calendars()}), 200
    except GoogleApiFehler:
        return (
            jsonify(
                {"error": "Google ist gerade nicht erreichbar. Bitte später erneut versuchen."}
            ),
            502,
        )


@google_bp.route("/calendars/check", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN")
def check_calendar():
    data = request.get_json(silent=True) or {}
    kalender_id = data.get("calendar_id")
    if not isinstance(kalender_id, str) or not kalender_id.strip() or len(kalender_id) > 255:
        return jsonify({"error": "Bitte eine gültige Kalender-ID angeben."}), 400
    ok, rolle, meldung = GoogleCalendarService().check_calendar(kalender_id.strip())
    antwort = {"ok": ok, "message": meldung}
    if ok:
        antwort["access_role"] = rolle
    return jsonify(antwort), 200


def _sichtbare_benutzer_ids(angefragt: list[int]) -> set[int]:
    """Wessen Google-Termine darf der eingeloggte Benutzer sehen?

    Gleiche Regeln wie bei den Terminen: Trainer nur sich selbst, Teamleitung das eigene
    Team (und sich selbst), CEO/ADMIN alle.
    """
    rolle = current_user.role.name
    if rolle in {RoleEnum.CEO.value, RoleEnum.ADMIN.value}:
        return set(angefragt)
    erlaubt = {current_user.id}
    if rolle == RoleEnum.TEAM_LEADER.value and current_user.team_id is not None:
        erlaubt |= {
            uid
            for (uid,) in User.query.with_entities(User.id).filter(
                User.team_id == current_user.team_id
            )
        }
    return set(angefragt) & erlaubt


@google_bp.route("/events", methods=["GET"])
@jwt_required()
def events():
    """Termine aus dem zugeordneten Google-Kalender von Mitarbeitern (nur lesend).

    Query: start, end (ISO-8601, max. 62 Tage), optional user_ids=1,2 (Standard: man selbst).
    Antwort: {connected, events: {"<user_id>": [...]}, errors: {"<user_id>": "..."}}
    Termine, die die App selbst in Google übertragen hat, fehlen bewusst – sie stehen
    schon als App-Termin im Kalender.
    """
    try:
        start = parse_iso_datetime(request.args.get("start"))
        ende = parse_iso_datetime(request.args.get("end"))
    except ValueError:
        return jsonify({"error": "start und end müssen ISO-8601-Zeitpunkte sein."}), 400
    if ende <= start or ende - start > _MAX_ZEITRAUM:
        return jsonify({"error": "Ungültiger Zeitraum (maximal 62 Tage)."}), 400

    roh = request.args.get("user_ids", "")
    try:
        angefragt = [int(x) for x in roh.split(",") if x.strip()][:50] if roh else [current_user.id]
    except ValueError:
        return jsonify({"error": "user_ids muss eine kommagetrennte Liste von Zahlen sein."}), 400

    google = GoogleCalendarService()
    if not google.verfuegbar:
        return jsonify({"connected": False, "events": {}, "errors": {}}), 200

    ids = _sichtbare_benutzer_ids(angefragt)
    benutzer = (
        User.query.filter(User.id.in_(ids), User.google_calendar_id.isnot(None)).all()
        if ids
        else []
    )
    termine, fehler = google.list_events([u.google_calendar_id for u in benutzer], start, ende)

    # Kunde im Titel erkennen, z. B. "(GFN)" -> Logo/Tag am Termin.
    tagger = CustomerTagger()
    # Von der App übertragene Termine auslassen – auch ältere ohne Markierung in Google.
    eigene = {
        gid
        for (gid,) in db.session.query(Event.google_event_id).filter(
            Event.google_event_id.isnot(None)
        )
    }
    return (
        jsonify(
            {
                "connected": True,
                "events": {
                    str(u.id): [
                        {**t, "tag": tagger.for_title(t["title"])}
                        for t in termine.get(u.google_calendar_id, [])
                        if t["id"] not in eigene
                    ]
                    for u in benutzer
                },
                "errors": {
                    str(u.id): fehler[u.google_calendar_id]
                    for u in benutzer
                    if u.google_calendar_id in fehler
                },
            }
        ),
        200,
    )
