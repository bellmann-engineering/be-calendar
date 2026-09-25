"""
Kunden/Projekte verwalten (CRUD, Logo) und Kunden in Termintiteln erkennen.

Wer benutzt sie?
    ``app/routes/customer_routes.py`` -> /api/v1/customers (Seite "Kunden") sowie
    ``event_routes.py`` und ``google_routes.py`` (CustomerTagger für die Logos am Termin).

Womit spricht sie?
    Tabelle ``customers``. Beim Löschen werden Termine des Kunden nicht gelöscht,
    sondern verlieren nur die Zuordnung (customer_id = NULL).

Validierung:
    ``color_hex`` muss exakt ``#RRGGBB`` sein. Der Wert landet im Frontend in einem
    style-Attribut – ohne Prüfung wäre dort CSS/HTML-Injection möglich.

Logos:
    Hochgeladene Bilder (PNG, JPEG, WebP, GIF) werden mit Pillow geöffnet, auf höchstens
    256 px verkleinert und als NEUES PNG gespeichert. Es wird also nie die Originaldatei
    ausgeliefert – eingeschmuggelte Inhalte (Metadaten, Polyglot-Dateien) fallen weg.
    SVG ist bewusst nicht erlaubt: Es kann JavaScript enthalten.
"""

import io
import re

from flask import url_for
from PIL import Image, UnidentifiedImageError

from app import db
from app.models import Event
from app.models.customer import Customer
from app.utils.time import utc_now

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_DEFAULT_COLOR = "#2B6CB0"
_MAX_CODE_LENGTH = 40
_LOGO_MAX_SIZE = (256, 256)
# Schutz vor "Dekompressionsbomben": winzige Datei, riesiges Bild im Speicher.
_LOGO_MAX_PIXELS = 25_000_000
_LOGO_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
# Klammerinhalt im Titel: "Schulung (GFN)" -> "GFN", "(Comcave/CC)" -> "Comcave/CC".
_BRACKETS = re.compile(r"\(([^()]{1,80})\)")
_SEPARATORS = re.compile(r"[/,;+&|]")

# (JSON-Antwort, HTTP-Status)
CustomerResult = tuple[dict, int]


def _clean(data: dict, key: str, default: str = "") -> str:
    """Liest ein String-Feld aus dem Request, trimmt es und ersetzt None/Nicht-Strings."""
    value = data.get(key, default)
    return value.strip() if isinstance(value, str) else default


def _parse_codes(raw: object) -> tuple[str | None, str | None]:
    """Kürzel aus Text ("GFN, Comcave") oder Liste -> (gespeicherter Text, Fehler)."""
    if raw is None or raw == "":
        return None, None
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, list) and all(isinstance(x, str) for x in raw):
        items = raw
    else:
        return None, "Kürzel müssen als Text angegeben werden."
    codes: list[str] = []
    for item in items:
        code = item.strip()
        if not code:
            continue
        if len(code) > _MAX_CODE_LENGTH or _SEPARATORS.search(code) or "(" in code or ")" in code:
            return (
                None,
                f"Ungültiges Kürzel „{code[:_MAX_CODE_LENGTH]}“ (ohne / ( ) und max. 40 Zeichen).",
            )
        if code.lower() not in {c.lower() for c in codes}:
            codes.append(code)
    text = ", ".join(codes)
    if len(text) > 255:
        return None, "Zu viele Kürzel (insgesamt max. 255 Zeichen)."
    return text or None, None


def _validate(name: str, email: str, color: str) -> str | None:
    """Gemeinsame Feldprüfung für Anlegen und Ändern."""
    if not name:
        return "Name ist erforderlich."
    if len(name) > 150 or len(email) > 150:
        return "Name und E-Mail dürfen höchstens 150 Zeichen lang sein."
    if not _HEX_COLOR.match(color):
        return "Die Farbe muss im Format #RRGGBB angegeben werden."
    return None


def logo_url(customer: Customer) -> str | None:
    """URL des Logos inkl. Version (?v=) – ändert sich bei jedem Upload (Browser-Cache)."""
    if customer.logo_updated_at is None:
        return None
    return url_for(
        "customers.get_logo", c_id=customer.id, v=int(customer.logo_updated_at.timestamp())
    )


def _serialize(c: Customer) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "email": c.email,
        "color_hex": c.color_hex,
        "short_codes": c.codes,
        "logo_url": logo_url(c),
    }


class CustomerService:
    """CRUD-Logik für Kunden."""

    @staticmethod
    def get_all() -> list[dict]:
        """Alle Kunden alphabetisch (für Kundenliste und Termin-Formular)."""
        return [_serialize(c) for c in Customer.query.order_by(Customer.name).all()]

    @staticmethod
    def create(data: dict) -> CustomerResult:
        """Legt einen Kunden an."""
        name = _clean(data, "name")
        email = _clean(data, "email")
        color = _clean(data, "color_hex", _DEFAULT_COLOR) or _DEFAULT_COLOR
        error = _validate(name, email, color)
        codes, codes_error = _parse_codes(data.get("short_codes"))
        if error or codes_error:
            return {"error": error or codes_error}, 400

        customer = Customer(name=name, email=email or None, color_hex=color, short_codes=codes)
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
        codes, codes_error = (
            _parse_codes(data.get("short_codes"))
            if "short_codes" in data
            else (customer.short_codes, None)
        )
        if error or codes_error:
            return {"error": error or codes_error}, 400

        customer.name = name
        customer.email = email or None
        customer.color_hex = color
        customer.short_codes = codes
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

    # ------------------------------------------------------------------ Logo
    @staticmethod
    def set_logo(c_id: int, file_storage: object) -> CustomerResult:
        """Speichert ein Logo (neu kodiert als PNG, max. 256 px)."""
        customer = db.session.get(Customer, c_id)
        if not customer:
            return {"error": "Kunde nicht gefunden."}, 404
        try:
            with Image.open(file_storage.stream) as bild:
                if bild.format not in _LOGO_FORMATS:
                    return {"error": "Bitte ein PNG-, JPEG-, WebP- oder GIF-Bild hochladen."}, 400
                if bild.width * bild.height > _LOGO_MAX_PIXELS:
                    return {"error": "Das Bild ist zu groß (max. 25 Megapixel)."}, 400
                bild.seek(0)  # bei animierten GIFs: erstes Bild
                bild = bild.convert("RGBA")
                bild.thumbnail(_LOGO_MAX_SIZE, Image.LANCZOS)
                puffer = io.BytesIO()
                bild.save(puffer, format="PNG", optimize=True)
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            return {"error": "Die Datei ist kein lesbares Bild."}, 400
        customer.logo_png = puffer.getvalue()
        customer.logo_updated_at = utc_now()
        db.session.commit()
        return {"message": "Logo gespeichert.", "logo_url": logo_url(customer)}, 200

    @staticmethod
    def delete_logo(c_id: int) -> CustomerResult:
        customer = db.session.get(Customer, c_id)
        if not customer:
            return {"error": "Kunde nicht gefunden."}, 404
        customer.logo_png = None
        customer.logo_updated_at = None
        db.session.commit()
        return {"message": "Logo entfernt."}, 200

    @staticmethod
    def get_logo(c_id: int) -> bytes | None:
        customer = db.session.get(Customer, c_id)
        return customer.logo_png if customer else None


class CustomerTagger:
    """Findet den Kunden zu einem Termin – für das kleine Logo/Tag im Kalender.

    1. Termin mit ``customer_id`` (in der App angelegt) -> dieser Kunde.
    2. Sonst Klammerinhalte im Titel: "Schulung (GFN)" oder "(Comcave/CC)". Jeder Teil
       wird mit Namen und Kürzeln aller Kunden verglichen (ohne Groß-/Kleinschreibung).

    Einmal pro Request erzeugen (lädt alle Kunden in EINER Abfrage, ohne Logos).
    """

    def __init__(self) -> None:
        self.by_id: dict[int, Customer] = {}
        self.by_alias: dict[str, tuple[Customer, str]] = {}
        for c in Customer.query.all():
            self.by_id[c.id] = c
            for alias in [c.name, *c.codes]:
                self.by_alias.setdefault(alias.strip().lower(), (c, alias.strip()))

    def _tag(self, customer: Customer, label: str | None = None) -> dict:
        return {
            "customer_id": customer.id,
            "name": customer.name,
            # Anzeige ohne Logo: das gefundene Kürzel, sonst das erste Kürzel oder der Name.
            "label": label or (customer.codes[0] if customer.codes else customer.name),
            "color": customer.color_hex if _HEX_COLOR.match(customer.color_hex or "") else None,
            "logo_url": logo_url(customer),
        }

    def for_title(self, title: str | None) -> dict | None:
        for inhalt in _BRACKETS.findall(title or ""):
            for teil in _SEPARATORS.split(inhalt):
                treffer = self.by_alias.get(teil.strip().lower())
                if treffer:
                    customer, alias = treffer
                    return self._tag(customer, alias if alias != customer.name else None)
        return None

    def for_event(self, customer_id: int | None, title: str | None) -> dict | None:
        if customer_id and customer_id in self.by_id:
            return self._tag(self.by_id[customer_id])
        return self.for_title(title)
