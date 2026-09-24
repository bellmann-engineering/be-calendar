import os
from google.oauth2 import service_account
from googleapiclient.discovery import build


class GoogleCalendarService:
    def __init__(self):
        self.credentials_path = os.path.join(os.getcwd(), "google_credentials.json")
        self.scopes = ["https://www.googleapis.com/auth/calendar"]
        self.credentials = None
        self.service = None
        self._authenticate()

    def _authenticate(self):
        if os.path.exists(self.credentials_path):
            self.credentials = service_account.Credentials.from_service_account_file(
                self.credentials_path, scopes=self.scopes
            )
            self.service = build("calendar", "v3", credentials=self.credentials)
        else:
            print(
                "WARNUNG: google_credentials.json im Hauptverzeichnis nicht gefunden!"
            )

    def get_busy_times(self, calendar_id, time_min, time_max):
        if not self.service:
            return []
        try:
            body = {
                "timeMin": time_min.isoformat() + "Z",
                "timeMax": time_max.isoformat() + "Z",
                "items": [{"id": calendar_id}],
            }
            eventsResult = self.service.freebusy().query(body=body).execute()
            return eventsResult["calendars"][calendar_id]["busy"]
        except Exception as e:
            print(f"Fehler beim Abruf von {calendar_id}: {e}")
            return []

    def insert_event(self, calendar_id, title, start_time, end_time, description=""):
        if not self.service:
            return None
        try:
            event_body = {
                "summary": title,
                "description": description
                or "Automatisch erstellt via Bellmann Dashboard",
                "start": {"dateTime": start_time.isoformat() + "Z", "timeZone": "UTC"},
                "end": {"dateTime": end_time.isoformat() + "Z", "timeZone": "UTC"},
            }
            event = (
                self.service.events()
                .insert(calendarId=calendar_id, body=event_body)
                .execute()
            )
            print(f"✅ Event in Google Kalender {calendar_id} erstellt!")
            return event.get("id")
        except Exception as e:
            print(f"❌ Fehler beim Schreiben in Google Kalender: {e}")
            return None

    def delete_event(self, calendar_id, event_id):
        if not self.service or not event_id:
            return
        try:
            self.service.events().delete(
                calendarId=calendar_id, eventId=event_id
            ).execute()
        except Exception:
            pass
