"""
Kunden/Projekte verwalten (CRUD) – jeder Kunde hat eine Kalenderfarbe.

Wer benutzt sie?
    ``app/routes/customer_routes.py`` -> /api/v1/customers (Seite "Kunden").

Womit spricht sie?
    Tabelle ``customers``. Beim Löschen werden Termine des Kunden nicht gelöscht,
    sondern verlieren nur die Zuordnung (customer_id = NULL).

Validierung:
    ``color_hex`` muss exakt ``#RRGGBB`` sein. Der Wert landet im Frontend in einem
    style-Attribut – ohne Prüfung wäre dort CSS/HTML-Injection möglich.
"""

import re

from app import db
from app.models import Event
from app.models.customer import Customer

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_DEFAULT_COLOR = "#2B6CB0"

# (JSON-Antwort, HTTP-Status)
CustomerResult = tuple[dict, int]


def _clean(data: dict, key: str, default: str = "") -> str:
    """Liest ein String-Feld aus dem Request, trimmt es und ersetzt None/Nicht-Strings."""
    value = data.get(key, default)
    return value.strip() if isinstance(value, str) else default


def _validate(name: str, email: str, color: str) -> str | None:
    """Gemeinsame Feldprüfung für Anlegen und Ändern."""
    if not name:
        return "Name ist erforderlich."
    if len(name) > 150 or len(email) > 150:
        return "Name und E-Mail dürfen höchstens 150 Zeichen lang sein."
    if not _HEX_COLOR.match(color):
        return "Die Farbe muss im Format #RRGGBB angegeben werden."
    return None


class CustomerService:
    """CRUD-Logik für Kunden."""

    @staticmethod
    def get_all() -> list[dict]:
        """Alle Kunden alphabetisch (für Kundenliste und Termin-Formular)."""
        return [
            {"id": c.id, "name": c.name, "email": c.email, "color_hex": c.color_hex}
            for c in Customer.query.order_by(Customer.name).all()
        ]

    @staticmethod
    def create(data: dict) -> CustomerResult:
        """Legt einen Kunden an."""
        name = _clean(data, "name")
        email = _clean(data, "email")
        color = _clean(data, "color_hex", _DEFAULT_COLOR) or _DEFAULT_COLOR
        error = _validate(name, email, color)
        if error:
            return {"error": error}, 400

        customer = Customer(name=name, email=email or None, color_hex=color)
        db.session.add(customer)
        db.session.commit()
        return {"message": "Kunde erfolgreich angelegt.", "id": customer.id}, 201

    @staticmethod
    def update(c_id: int, data: dict) -> CustomerResult:
        """Ändert einen Kunden (nur mitgeschickte Felder)."""
        customer = db.session.get(Customer, c_id)
        if not customer:
            return {"error": "Kunde nicht gefunden."}, 404

        name = _clean(data, "name", customer.name) if "name" in data else customer.name
        email = _clean(data, "email") if "email" in data else (customer.email or "")
        color = _clean(data, "color_hex") if "color_hex" in data else customer.color_hex
        error = _validate(name, email, color or "")
        if error:
            return {"error": error}, 400

        customer.name = name
        customer.email = email or None
        customer.color_hex = color
        db.session.commit()
        return {"message": "Kunde aktualisiert.", "id": customer.id}, 200

    @staticmethod
    def delete(c_id: int) -> CustomerResult:
        """Löscht einen Kunden; seine Termine bleiben bestehen (ohne Kundenzuordnung)."""
        customer = db.session.get(Customer, c_id)
        if not customer:
            return {"error": "Kunde nicht gefunden."}, 404
        # Ohne dieses UPDATE würde der Fremdschlüssel das Löschen verhindern (-> 500).
        Event.query.filter_by(customer_id=c_id).update({Event.customer_id: None})
        db.session.delete(customer)
        db.session.commit()
        return {"message": "Kunde gelöscht."}, 200
