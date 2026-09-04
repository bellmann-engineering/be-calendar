from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.services.ai_service import AIService
import json

ai_bp = Blueprint("ai", __name__, url_prefix="/api/v1/ai")


@ai_bp.route("/analyze-conflicts", methods=["POST"])
@jwt_required()
def analyze_conflicts():
    """Nimmt Kalenderdaten entgegen und gibt den KI-Bericht zurück."""
    data = request.get_json()
    if not data or "calendar_data" not in data:
        return jsonify({"error": "Fehlende Kalenderdaten im Request-Body."}), 400

    calendar_data_json = json.dumps(data["calendar_data"])

    analysis_result = AIService.analyze_conflicts(calendar_data_json)
    if analysis_result is None:
        return (
            jsonify({"error": "KI-Dienst nicht erreichbar. Läuft Ollama lokal?"}),
            500,
        )

    return jsonify({"analysis": analysis_result}), 200
