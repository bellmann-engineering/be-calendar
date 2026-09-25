"""
Tabelle ``customers`` – externe Kunden/Projekte, jeweils mit Kalenderfarbe und optional Logo.

Beziehungen:
    * 1:n ``events`` über ``events.customer_id`` (Rückreferenz ``customer.events``)

Wer benutzt das Model?
    CustomerService (CRUD und Logo über /api/v1/customers), die Terminliste
    (``GET /api/v1/events`` liefert ``color`` = Farbe des Kunden) und CustomerTagger:
    Steht im Titel eines Termins z. B. "(GFN)" oder "(Comcave/CC)", wird der Kunde über
    Name oder Kürzel erkannt und sein Logo klein am Termin angezeigt.
"""

from sqlalchemy.orm import deferred

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
    # Kürzel/Schreibweisen, unter denen der Kunde in Termintiteln steht, kommagetrennt,
    # z. B. "Comcave, CC". Der Name selbst zählt immer mit.
    short_codes = db.Column(db.String(255), nullable=True)
    # Logo als kleines PNG (serverseitig neu kodiert, max. 256 px). deferred: wird nur
    # geladen, wenn es wirklich gebraucht wird – nicht bei jeder Kundenliste.
    logo_png = deferred(db.Column(db.LargeBinary, nullable=True))
    # Zeitpunkt des Uploads – dient auch als Versionsnummer in der Logo-URL (Cache).
    logo_updated_at = db.Column(db.DateTime(timezone=True), nullable=True)

    @property
    def codes(self) -> list[str]:
        """Kürzel als Liste (ohne leere Einträge)."""
        return [c.strip() for c in (self.short_codes or "").split(",") if c.strip()]

    def __repr__(self) -> str:
        return f"<Customer {self.name}>"
