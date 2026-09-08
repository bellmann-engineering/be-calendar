from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.ai_service import AIService
from app.services.event_service import EventService
from datetime import datetime, timedelta, timezone
import json

ai_bp = Blueprint("ai", __name__, url_prefix="/api/v1/ai")


@ai_bp.route("/analyze", methods=["POST"])
@jwt_required()
def analyze_conflicts():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Fehlende Daten im Request-Body."}), 400

    timeframe = data.get("timeframe", "visible")

    if timeframe == "visible":
        events_to_analyze = data.get("events", [])
    else:
        user_id = int(get_jwt_identity())
        all_events, error_message, _ = EventService.list_visible_events(user_id)

        if error_message:
            return jsonify({"error": error_message}), 400

        # LÖSUNG: Zeitzone entfernen, um mit der DB vergleichen zu können
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        if timeframe == "day":
            end_date = now + timedelta(days=1)
        elif timeframe == "week":
            end_date = now + timedelta(weeks=1)
        elif timeframe == "month":
            end_date = now + timedelta(days=30)
        else:
            end_date = now + timedelta(weeks=1)

        events_to_analyze = [
            {
                "title": e.title,
                "start": e.start_time.isoformat(),
                "end": e.end_time.isoformat(),
                "assigned_to": e.assigned_to_id,
            }
            for e in all_events
            if e.start_time and now <= e.start_time <= end_date
        ]

    if not events_to_analyze:
        return (
            jsonify(
                {
                    "analysis": "<strong>Keine Termine</strong> im gewählten Zeitraum gefunden. Es gibt keine Konflikte."
                }
            ),
            200,
        )

    calendar_data_json = json.dumps(events_to_analyze)
    analysis_result = AIService.analyze_conflicts(calendar_data_json, timeframe)

    if analysis_result is None:
        return jsonify({"error": "KI-Dienst nicht erreichbar. Bitte Log prüfen."}), 500

    return jsonify({"analysis": analysis_result}), 200
