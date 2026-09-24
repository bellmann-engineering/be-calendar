"""
Tabelle ``customers`` – externe Kunden/Projekte, jeweils mit einer Kalenderfarbe.

Beziehungen:
    * 1:n ``events`` über ``events.customer_id`` (Rückreferenz ``customer.events``)

Wer benutzt das Model?
    CustomerService (CRUD über /api/v1/customers) und die Terminliste
    (``GET /api/v1/events`` liefert ``color`` = Farbe des Kunden).
"""

from app import db


class Customer(db.Model):
    """Ein Kunde bzw. Projekt; ``color_hex`` färbt dessen Termine im Kalender ein."""

    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    # Format "#RRGGBB" – wird im CustomerService per Regex validiert, weil der Wert im
    # Frontend in ein style-Attribut geschrieben wird (sonst CSS/HTML-Injection möglich).
    color_hex = db.Column(db.String(7), default="#2B6CB0")

    def __repr__(self) -> str:
        return f"<Customer {self.name}>"
