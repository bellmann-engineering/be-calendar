"""
"Erst speichern, dann nach außen reden": Aktionen NACH einem erfolgreichen Commit.

Problem, das diese Datei löst:
    Früher wurden E-Mails (SMTP) und Google-Kalender-Löschungen MITTEN in der offenen
    Datenbank-Transaktion ausgeführt. Folgen:
      * Eine langsame SMTP-Verbindung hielt DB-Verbindung und Transaktion offen.
      * Schlug der Commit danach fehl, war die E-Mail trotzdem schon verschickt
        ("Ihnen wurde ein Termin zugewiesen" – obwohl der Termin nie gespeichert wurde).

Lösung:
    Services registrieren Nebenwirkungen mit ``call_after_commit(funktion)``. Die Funktion
    wird im ``db.session.info``-Speicher der aktuellen Session geparkt und erst ausgeführt,
    wenn SQLAlchemy das Event ``after_commit`` feuert. Bei einem Rollback wird die Liste
    verworfen – dann passiert gar nichts.

Wer benutzt sie?
    ``app/services/email_service.py`` (queue_email) und
    ``app/services/event_service.py`` (Google-Kalender-Löschung).

Wovon hängt sie ab?
    SQLAlchemy-Session-Events. Achtung: Innerhalb von ``after_commit`` darf KEIN SQL
    ausgeführt werden – die Callbacks dürfen nur "nach außen" sprechen (SMTP, HTTP).
"""

import logging
from collections.abc import Callable

from sqlalchemy import event
from sqlalchemy.orm import Session

from app import db

logger = logging.getLogger(__name__)

_KEY = "after_commit_callbacks"


def call_after_commit(callback: Callable[[], None]) -> None:
    """Merkt ``callback`` vor; er läuft genau einmal nach dem nächsten erfolgreichen Commit."""
    db.session.info.setdefault(_KEY, []).append(callback)


@event.listens_for(Session, "after_commit")
def _run_after_commit(session: Session) -> None:
    """SQLAlchemy-Hook: Führt alle vorgemerkten Callbacks aus (Fehler werden nur geloggt)."""
    callbacks = session.info.pop(_KEY, [])
    for callback in callbacks:
        try:
            callback()
        except Exception:  # noqa: BLE001 - Nebenwirkung darf den Request nie abbrechen
            logger.exception("After-Commit-Aktion fehlgeschlagen")


@event.listens_for(Session, "after_soft_rollback")
def _discard_on_rollback(session: Session, _previous_transaction: object) -> None:
    """Bei Rollback: vorgemerkte Nebenwirkungen verwerfen – es wurde ja nichts gespeichert."""
    session.info.pop(_KEY, None)
