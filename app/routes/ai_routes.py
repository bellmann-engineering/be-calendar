from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.services.ai_service import AIService
import json

ai_bp = Blueprint("ai", __name__, url_prefix="/api/v1/ai")


@ai_bp.route("/analyze", methods=["POST"])
@jwt_required()
def analyze_conflicts():
    """Nimmt Kalenderdaten (events) entgegen und gibt den KI-Bericht zurück."""
    data = request.get_json()
    if not data or "events" not in data:
        return jsonify({"error": "Fehlende Kalenderdaten im Request-Body."}), 400

    # Events als JSON-String an den AI-Service übergeben
    calendar_data_json = json.dumps(data["events"])

    analysis_result = AIService.analyze_conflicts(calendar_data_json)
    if analysis_result is None:
        return jsonify({"error": "KI-Dienst nicht erreichbar. Bitte Log prüfen."}), 500

    return jsonify({"analysis": analysis_result}), 200
