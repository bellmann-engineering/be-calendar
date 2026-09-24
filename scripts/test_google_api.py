import sys
from datetime import datetime, timedelta
from app.services.calendar_service import GoogleCalendarService


def test(calendar_id):
    print(f"\n[1] Starte Test für Kalender: {calendar_id}")
    service = GoogleCalendarService()

    if not service.service:
        print(
            "[!] ABBRUCH: Bot konnte nicht bei Google einloggen. Fehlt die google_credentials.json?"
        )
        return

    print("[2] Bot erfolgreich authentifiziert! Frage die nächsten 7 Tage ab...")
    now = datetime.utcnow()
    time_max = now + timedelta(days=7)

    busy = service.get_busy_times(calendar_id, now, time_max)

    print("\n--- ERGEBNIS AUS DEM GOOGLE KALENDER ---")
    if busy:
        for b in busy:
            print(f"Gebucht: {b['start']} bis {b['end']}")
    else:
        print("Keine Termine gefunden.")
        print(
            "WICHTIG: Ist der Kalender leer ODER hast du vergessen, ihn in Google für die Bot-Emailadresse freizugeben?"
        )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        test(sys.argv[1])
    else:
        print("Fehler: Bitte übergib deine Kalender-ID (E-Mail).")
        print("Beispiel: python test_google_api.py max.mustermann@gmail.com")
