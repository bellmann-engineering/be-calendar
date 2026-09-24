"""
HTTP-Endpunkte für Termine und das Audit-Log (/api/v1/events/...).

Wer ruft sie auf?
    ``app.js`` (Dashboard-Kalender: laden, anlegen, bearbeiten, löschen, neu zuweisen),
    ``compare.html`` (Vergleichsansicht), ``logs.html`` (Audit-Log).

Wovon hängt die Datei ab?
    EventService (gesamte Logik), ``@role_required``, ``current_user`` (app/security.py).

Datumsformat: Alle Zeiten gehen als ISO-8601 in UTC mit Offset raus ("...+00:00").
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import current_user, jwt_required
from sqlalchemy.orm import joinedload

from app import db
from app.decorators.auth import role_required
from app.models import AuditLog, Event, User
from app.services.event_service import EventService
from app.utils.time import isoformat_utc

event_bp = Blueprint("events", __name__, url_prefix="/api/v1/events")

DEFAULT_COLOR = "#2B6CB0"


def serialize_event(event: Event, rejection_reason: str | None = None) -> dict:
    """Einheitliche JSON-Darstellung eines Termins (für Liste, Anlegen, Ändern).

    ``event.customer`` wurde in der Liste per joinedload vorab geladen -> kein Extra-SQL.
    """
    color = DEFAULT_COLOR
    if event.customer is not None and event.customer.color_hex:
        color = event.customer.color_hex
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "start_time": isoformat_utc(event.start_time),
        "end_time": isoformat_utc(event.end_time),
        "assigned_to_id": event.assigned_to_id,
        "meeting_link": event.meeting_link,
        "reallocation_required": event.reallocation_required,
        "buffer_before_mins": event.buffer_before_mins,
        "buffer_after_mins": event.buffer_after_mins,
        "is_all_day": event.is_all_day,
        "customer_id": event.customer_id,
        "color": color,
        "rejection_reason": rejection_reason,
        # Pflichttermine sind im Frontend vorgesehen, aber noch nicht im Datenmodell.
        "is_mandatory": False,
    }


@event_bp.route("", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN", "TEAM_LEADER")
def create_event():
    """Legt einen Termin an. Pflichtfelder: title, start_time, end_time."""
    data = request.get_json(silent=True) or {}
    if not all(field in data for field in ("title", "start_time", "end_time")):
        return jsonify({"error": "Pflichtfelder fehlen: title, start_time, end_time"}), 400

    event, error_message, status_code = EventService.create_event(data, current_user.id)
    if error_message:
        return (
            jsonify({"error": "Terminerstellung fehlgeschlagen", "message": error_message}),
            status_code,
        )
    return (
        jsonify({"message": "Termin erfolgreich erstellt.", "event": serialize_event(event)}),
        201,
    )


@event_bp.route("", methods=["GET"])
@jwt_required()
def list_events():
    """Sichtbare Termine, optional gefiltert über ?start=...&end=... (ISO-8601).

    Zwei SQL-Abfragen, egal wie viele Termine: (1) Termine inkl. Kunde per JOIN,
    (2) alle Ablehnungsgründe für die Termine mit reallocation_required.
    """
    events, error_message, status_code = EventService.list_visible_events(
        current_user.id, request.args.get("start"), request.args.get("end")
    )
    if error_message:
        return jsonify({"error": error_message}), status_code

    reasons = EventService.latest_rejection_reasons(
        [e.id for e in events if e.reallocation_required]
    )
    return jsonify([serialize_event(e, reasons.get(e.id)) for e in events]), 200


@event_bp.route("/<int:event_id>", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN", "TEAM_LEADER")
def update_event(event_id: int):
    """Ändert einen Termin (Teil-Update)."""
    data = request.get_json(silent=True) or {}
    event, error_message, status_code = EventService.update_event(
        event_id=event_id, data=data, user_id=current_user.id
    )
    if error_message:
        return (
            jsonify({"error": "Terminaktualisierung fehlgeschlagen", "message": error_message}),
            status_code,
        )
    return (
        jsonify({"message": "Termin erfolgreich aktualisiert.", "event": serialize_event(event)}),
        200,
    )


@event_bp.route("/<int:event_id>", methods=["DELETE"])
@jwt_required()
@role_required("CEO", "ADMIN", "TEAM_LEADER")
def delete_event(event_id: int):
    """Soft-Delete eines Termins."""
    success, error_message, status_code = EventService.soft_delete_event(event_id, current_user.id)
    if not success:
        return jsonify({"error": error_message}), status_code
    return jsonify({"message": f"Termin {event_id} erfolgreich gelöscht."}), status_code


@event_bp.route("/audit", methods=["GET"])
@jwt_required()
@role_required("CEO", "ADMIN")
def get_audit():
    """Die neuesten 1000 Audit-Einträge inkl. Name und Rolle des Ausführenden.

    ``details`` wird als echtes JSON-Objekt geliefert (früher ``str(dict)`` im
    Python-Format, das das Frontend mühsam "reparieren" musste).
    """
    rows = (
        db.session.query(AuditLog, User)
        .outerjoin(User, AuditLog.user_id == User.id)
        .options(joinedload(User.role))
        .order_by(AuditLog.timestamp.desc())
        .limit(1000)
        .all()
    )
    return (
        jsonify(
            [
                {
                    "timestamp": isoformat_utc(log.timestamp),
                    "user_name": user.full_name if user else "System",
                    "role": user.role.name if user else "SYSTEM",
                    "action": log.action,
                    "details": log.details_json or None,
                }
                for log, user in rows
            ]
        ),
        200,
    )
