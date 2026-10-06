"""
HTTP-Endpunkte für andere Anwendungen (/api/v1/integration/...), z. B. die Urlaubsantrags-App.

Wer ruft sie auf?
    Server-zu-Server aus einem anderen Container, NICHT vom Browser. Der Aufruf geht
    direkt an den Container (``http://bellmann_web:5000/api/v1/integration/...``, beide
    hängen im ``traefik_network``) und umgeht damit Traefik/Authelia. Stattdessen
    authentifiziert ein gemeinsamer Schlüssel (``INTEGRATION_API_KEY``) im Header
    ``X-API-Key`` (oder ``Authorization: Bearer <Schlüssel>``).
    Ohne gesetzten Schlüssel ist die Schnittstelle abgeschaltet (404).

Endpunkte:
    GET  /availability?email=...&start=JJJJ-MM-TT&end=JJJJ-MM-TT
         -> {"email", "start", "end", "conflicts": [{"date", "events": [...]}]}
            ``conflicts`` ist leer, wenn die Person im Zeitraum nichts hat.
    POST /vacations  {"email", "start", "end", "title"?, "description"?}
         -> 201 {"message", "event": {...}}  (ganztägiger Termin)

Wovon hängt sie ab?
    integration_service (Logik), ``INTEGRATION_API_KEY`` (app/config.py).
"""

import hmac

from flask import Blueprint, current_app, jsonify, request

from app import limiter
from app.routes.event_routes import serialize_event
from app.services import integration_service as svc

integration_bp = Blueprint("integration", __name__, url_prefix="/api/v1/integration")


def _provided_key() -> str:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.headers.get("X-API-Key", "").strip()


@integration_bp.before_request
def _require_api_key():
    expected = current_app.config.get("INTEGRATION_API_KEY") or ""
    if not expected:
        return jsonify({"error": "Nicht gefunden."}), 404
    if not hmac.compare_digest(_provided_key().encode(), expected.encode()):
        return jsonify({"error": "Ungültiger oder fehlender API-Schlüssel."}), 401
    return None


@integration_bp.errorhandler(svc.IntegrationError)
def _integration_error(exc: svc.IntegrationError):
    return jsonify({"error": exc.message}), exc.status


@integration_bp.route("/availability", methods=["GET"])
@limiter.limit("120 per minute")
def availability():
    """Termine einer Person im Zeitraum (je Tag) – zum Anzeigen von Überschneidungen."""
    user = svc.find_user(request.args.get("email"))
    first, last = svc.parse_range(request.args.get("start"), request.args.get("end"))
    return (
        jsonify(
            {
                "email": user.email,
                "start": first.isoformat(),
                "end": last.isoformat(),
                "conflicts": svc.find_conflicts(user, first, last),
            }
        ),
        200,
    )


@integration_bp.route("/vacations", methods=["POST"])
@limiter.limit("60 per minute")
def create_vacation():
    """Trägt Urlaub als ganztägigen Termin in den Kalender der Person ein."""
    data = request.get_json(silent=True) or {}
    user = svc.find_user(data.get("email"))
    first, last = svc.parse_range(data.get("start"), data.get("end"))
    event = svc.create_vacation(user, first, last, data)
    return (
        jsonify({"message": "Urlaub eingetragen.", "event": serialize_event(event)}),
        201,
    )
