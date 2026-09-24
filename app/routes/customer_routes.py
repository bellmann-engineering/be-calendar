"""
HTTP-Endpunkte für Kunden/Projekte (/api/v1/customers).

Wer ruft sie auf?
    ``customers.html`` (Verwaltung, nur CEO/ADMIN) und ``app.js`` (Kunden-Dropdown im
    Termin-Formular, auch für Teamleitungen).

Wovon hängt die Datei ab?
    CustomerService (Validierung + DB), ``@role_required``.
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

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
