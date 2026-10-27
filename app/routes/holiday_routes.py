"""
Feiertage für das Kalender-Frontend (GET /api/v1/holidays?start=…&end=…).

Liefert gesetzliche und betriebliche Feiertage aus dem Urlaubsplaner (holiday_service),
damit der Kalender sie genauso markiert wie der Urlaubsplaner. Für alle angemeldeten
Benutzer; ``start``/``end`` wie bei /api/v1/events (ISO, nur der Tag zählt, ``end``
exklusiv wie bei FullCalendar).
"""

from datetime import date, timedelta

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.services.holiday_service import holidays_between

holiday_bp = Blueprint("holidays", __name__, url_prefix="/api/v1/holidays")

MAX_RANGE_DAYS = 2 * 366


def _day(name: str) -> date | None:
    try:
        return date.fromisoformat((request.args.get(name) or "").strip()[:10])
    except ValueError:
        return None


@holiday_bp.route("", methods=["GET"])
@jwt_required()
def list_holidays():
    start, end = _day("start"), _day("end")
    if start is None or end is None or end <= start:
        return jsonify({"error": "start und end (ISO-Datum, end exklusiv) angeben."}), 400
    if (end - start).days > MAX_RANGE_DAYS:
        return jsonify({"error": "Zeitraum höchstens zwei Jahre."}), 400
    rows, error = holidays_between(start, end - timedelta(days=1))
    return jsonify(
        {
            "holidays": [
                {"date": r["date"].isoformat(), "name": r["name"], "source": r["source"]} for r in rows
            ],
            "error": error,
        }
    ), 200
