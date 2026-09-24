"""
Symmetrische Verschlüsselung für Geheimnisse, die in der Datenbank liegen müssen.

Wofür?
    Das Google-Refresh-Token (siehe app/services/google_oauth_service.py) ist ein
    dauerhafter Zugang zu den Kalendern des verbundenen Google-Kontos. Es darf deshalb
    nie im Klartext in PostgreSQL stehen – ein Datenbank-Backup oder ein SQL-Zugriff
    allein soll nicht reichen, um an die Kalender zu kommen.

Wie?
    Fernet (Bibliothek ``cryptography``) = AES-128-CBC + HMAC-SHA256, also verschlüsselt
    UND manipulationssicher. Der Schlüssel wird per HKDF aus dem ``SECRET_KEY`` der App
    abgeleitet ("Key Derivation"): Datenbank und Schlüssel liegen so an verschiedenen
    Orten (.env vs. PostgreSQL).

Achtung:
    Wird ``SECRET_KEY`` geändert (rotiert), lassen sich gespeicherte Tokens nicht mehr
    entschlüsseln -> die Google-Verbindung muss dann einmal neu hergestellt werden.
    ``decrypt_text`` liefert in diesem Fall ``None`` statt abzustürzen.
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from flask import current_app

# "info" trennt diesen Schlüssel von anderen, die man evtl. später aus SECRET_KEY ableitet.
_INFO = b"bellmann-calendar/google-refresh-token/v1"


def _fernet() -> Fernet:
    """Fernet-Instanz mit einem aus SECRET_KEY abgeleiteten 32-Byte-Schlüssel."""
    geheim = current_app.config["SECRET_KEY"].encode("utf-8")
    schluessel = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(geheim)
    return Fernet(base64.urlsafe_b64encode(schluessel))


def encrypt_text(klartext: str) -> str:
    """Verschlüsselt einen Text; Ergebnis ist ein URL-sicherer ASCII-String."""
    return _fernet().encrypt(klartext.encode("utf-8")).decode("ascii")


def decrypt_text(geheimtext: str) -> str | None:
    """Entschlüsselt – oder None, wenn der Schlüssel nicht passt / Daten manipuliert sind."""
    try:
        return _fernet().decrypt(geheimtext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
