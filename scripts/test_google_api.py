"""
Manueller Verbindungstest für die Google-Calendar-Anbindung (kein pytest-Test!).

Aufruf:
    python scripts/test_google_api.py max.mustermann@gmail.com
    (in Docker: docker compose exec web python scripts/test_google_api.py <kalender-id>)

Was passiert?
    1. Lädt die Service-Account-Datei (GOOGLE_CREDENTIALS_FILE, Standard:
       ./google_credentials.json).
    2. Fragt die belegten Zeiten der nächsten 7 Tage über die Free/Busy-API ab.
    3. Gibt das Ergebnis aus. Leeres Ergebnis heißt oft: Der Kalender wurde nicht für
       die E-Mail-Adresse des Service-Accounts freigegeben.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

# Projektverzeichnis in den Suchpfad, damit "import app" auch aus scripts/ heraus klappt.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.services.calendar_service import GoogleCalendarService  # noqa: E402


def check_calendar(calendar_id: str) -> None:
    """Führt die Free/Busy-Abfrage für ``calendar_id`` aus und druckt das Ergebnis."""
    print(f"\n[1] Starte Test für Kalender: {calendar_id}")
    # GoogleCalendarService liest seine Einstellungen aus der Flask-Konfiguration.
    with create_app().app_context():
        service = GoogleCalendarService()
        if not service.service:
            print("[!] ABBRUCH: Anmeldung bei Google fehlgeschlagen. Fehlt die Credentials-Datei?")
            return

        print("[2] Erfolgreich authentifiziert! Frage die nächsten 7 Tage ab...")
        now = datetime.now(timezone.utc)
        busy = service.get_busy_times(calendar_id, now, now + timedelta(days=7))

    print("\n--- ERGEBNIS AUS DEM GOOGLE KALENDER ---")
    if busy:
        for block in busy:
            print(f"Gebucht: {block['start']} bis {block['end']}")
    else:
        print("Keine Termine gefunden.")
        print(
            "WICHTIG: Ist der Kalender leer ODER wurde er nicht für die "
            "Service-Account-Adresse freigegeben?"
        )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_calendar(sys.argv[1])
    else:
        print("Fehler: Bitte die Kalender-ID (E-Mail) übergeben.")
        print("Beispiel: python scripts/test_google_api.py max.mustermann@gmail.com")
