"""
Synchronisierung: Termine aus dem Kalender der Bellmann Engineering GmbH -> Google-Kalender der Mitarbeiter.

Eine einzige Funktion ``synchronisieren(event)`` entscheidet nach JEDER Änderung, was in
Google passieren muss. Sie vergleicht den Soll-Zustand mit dem, was zuletzt gespiegelt
wurde (``event.google_event_id`` + ``event.google_sync_calendar_id``):

    Soll-Kalender = Google-Kalender des zugewiesenen Mitarbeiters
                    (keiner, wenn der Termin gelöscht oder niemandem zugewiesen ist)

    | vorher gespiegelt in | Soll-Kalender | Aktion                                  |
    |----------------------|---------------|-----------------------------------------|
    | –                    | –             | nichts                                  |
    | –                    | K             | in K anlegen                            |
    | K                    | K             | in K ändern (Titel, Zeit, Beschreibung) |
    | K                    | L (anderer)   | in K löschen, in L anlegen (Neu-Zuweis.)|
    | K                    | –             | in K löschen (Absage, Löschen, …)       |

Wann wird sie aufgerufen?  Immer NACH dem erfolgreichen Commit der eigentlichen Änderung
(EventService: anlegen/ändern/löschen, RSVPService: Absage). Scheitert Google, bleibt der
Termin in unserer Datenbank trotzdem korrekt gespeichert – der Fehler wird nur geloggt.
Die neue Google-ID wird in einem zweiten, kleinen Commit festgehalten.
"""

from __future__ import annotations

import logging

from app import db
from app.models import Event

logger = logging.getLogger(__name__)


def _soll_kalender(event: Event) -> str | None:
    """In welchem Google-Kalender SOLL der Termin gerade stehen?"""
    if event.is_deleted or event.assigned_to is None:
        return None
    return event.assigned_to.google_calendar_id or None


def synchronisieren(event: Event) -> None:
    """Bringt die Google-Kopie des Termins auf den aktuellen Stand (Fehler nur geloggt)."""
    vorher_kalender = event.google_sync_calendar_id
    vorher_id = event.google_event_id
    soll = _soll_kalender(event)
    if not vorher_id and not soll:
        return  # nichts gespiegelt und nichts zu spiegeln -> Google gar nicht erst ansprechen

    from app.services.calendar_service import GoogleCalendarService

    google = GoogleCalendarService()
    if not google.verfuegbar:
        return

    try:
        if vorher_id and vorher_kalender and vorher_kalender == soll:
            # Gleicher Kalender -> nur aktualisieren.
            google.update_event(
                soll, vorher_id, event.title, event.start_time, event.end_time, event.description
            )
            return

        geaendert = False
        if vorher_id and vorher_kalender:
            # Alte Kopie entfernen (anderer Trainer, Absage oder gelöscht).
            google.delete_event(vorher_kalender, vorher_id)
            event.google_event_id = None
            event.google_sync_calendar_id = None
            geaendert = True
        if soll:
            neue_id = google.insert_event(
                soll, event.title, event.start_time, event.end_time, event.description
            )
            if neue_id:
                event.google_event_id = neue_id
                event.google_sync_calendar_id = soll
                geaendert = True
        if geaendert:
            db.session.commit()
    except Exception:  # noqa: BLE001 - Google darf nie einen gespeicherten Termin gefährden
        db.session.rollback()
        logger.exception("Google-Synchronisierung für Termin %s fehlgeschlagen", event.id)
