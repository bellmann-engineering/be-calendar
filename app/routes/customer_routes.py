"""
HTTP-Endpunkte für Kunden/Projekte (/api/v1/customers).

Wer ruft sie auf?
    ``customers.html`` (Verwaltung, nur CEO/ADMIN) und ``app.js`` (Kunden-Dropdown im
    Termin-Formular, auch für Teamleitungen). Die Logos (GET .../logo) lädt jeder
    angemeldete Benutzer als <img> im Kalender.

Wovon hängt die Datei ab?
    CustomerService (Validierung + DB), ``@role_required``.
"""

from flask import Blueprint, Response, jsonify, request
from flask_jwt_extended import jwt_required

from app import limiter
from app.decorators.auth import role_required
from app.services.customer_service import CustomerService

customer_bp = Blueprint("customers", __name__, url_prefix="/api/v1/customers")


@customer_bp.route("", methods=["GET"])
@jwt_required()
@role_required("CEO", "ADMIN", "TEAM_LEADER")
def list_customers():
    """Alle Kunden (Teamleitungen brauchen sie für das Termin-Formular)."""
    return jsonify(CustomerService.get_all()), 200


@customer_bp.route("", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN")
def create_customer():
    res, code = CustomerService.create(request.get_json(silent=True) or {})
    return jsonify(res), code


@customer_bp.route("/<int:c_id>", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN")
def update_customer(c_id: int):
    res, code = CustomerService.update(c_id, request.get_json(silent=True) or {})
    return jsonify(res), code


@customer_bp.route("/<int:c_id>", methods=["DELETE"])
@jwt_required()
@role_required("CEO", "ADMIN")
def delete_customer(c_id: int):
    res, code = CustomerService.delete(c_id)
    return jsonify(res), code


# ====================================================================== Logo
@customer_bp.route("/<int:c_id>/logo", methods=["GET"])
@jwt_required()
def get_logo(c_id: int):
    """Logo als PNG. Mit ?v=<Version> darf der Browser es dauerhaft zwischenspeichern."""
    png = CustomerService.get_logo(c_id)
    if not png:
        return jsonify({"error": "Kein Logo vorhanden."}), 404
    response = Response(png, mimetype="image/png")
    # private: nur im Browser des Benutzers, nicht in geteilten Proxy-Caches.
    response.headers["Cache-Control"] = (
        "private, max-age=31536000, immutable" if request.args.get("v") else "private, no-cache"
    )
    return response


@customer_bp.route("/<int:c_id>/logo", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN")
@limiter.limit("30 per hour")
def upload_logo(c_id: int):
    """Logo hochladen (multipart/form-data, Feld "file"; Größe begrenzt MAX_CONTENT_LENGTH)."""
    datei = request.files.get("file")
    if datei is None or not datei.filename:
        return jsonify({"error": "Keine Datei hochgeladen."}), 400
    res, code = CustomerService.set_logo(c_id, datei)
    return jsonify(res), code


@customer_bp.route("/<int:c_id>/logo", methods=["DELETE"])
@jwt_required()
@role_required("CEO", "ADMIN")
def delete_logo(c_id: int):
    res, code = CustomerService.delete_logo(c_id)
    return jsonify(res), code
