"""
Google-Konto verbinden (OAuth 2.0) – "ein Schlüssel für alle Kalender".

Ablauf (Authorization Code Flow mit PKCE):
    1. CEO/ADMIN klickt auf der Mitarbeiter-Seite "Mit Google verbinden"
       -> ``start()`` erzeugt die Google-Anmelde-URL und merkt sich in einer signierten
          Session (Cookie ``bellmann_oauth``, SameSite=Lax): state, PKCE-Verifier, User-ID.
    2. Der Browser geht zu accounts.google.com; Kai meldet sich an und erlaubt den Zugriff.
    3. Google leitet zurück auf ``/api/v1/google/oauth/callback?code=…&state=…``
       -> ``callback()`` prüft den state (Schutz gegen untergeschobene Anmeldungen/CSRF),
          tauscht den einmaligen Code gegen Tokens und speichert das Refresh-Token
          VERSCHLÜSSELT in ``google_connections``.
    4. Ab jetzt nutzt app/services/calendar_service.py diese Verbindung für alle Aufrufe.

Begriffe:
    * Access-Token: kurzlebig (ca. 1 h), wird automatisch erneuert, nur im Arbeitsspeicher.
    * Refresh-Token: dauerhaft, damit holt sich die App neue Access-Tokens – deshalb
      verschlüsselt gespeichert und beim Trennen bei Google widerrufen.
    * PKCE: Selbst wer den Code aus der Weiterleitung abfängt, kann ihn ohne den nur
      serverseitig bekannten "code_verifier" nicht einlösen.
    * state: Zufallswert, der beweist, dass die Rückkehr zu UNSERER Anmeldung gehört.

Wer benutzt diese Datei?  app/routes/google_routes.py
Womit spricht sie?        accounts.google.com, oauth2.googleapis.com, Tabelle google_connections
"""

from __future__ import annotations

import logging
import os
import secrets

import requests
from flask import current_app, session

from app import db
from app.models import AuditLog, GoogleConnection, RoleEnum, User
from app.services.calendar_service import OAUTH_SCOPES, TOKEN_URI, cache_leeren
from app.utils.crypto import decrypt_text, encrypt_text
from app.utils.time import isoformat_utc

logger = logging.getLogger(__name__)

_SESSION_KEY = "google_oauth"
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_USERINFO_URI = "https://openidconnect.googleapis.com/v1/userinfo"
_REVOKE_URI = "https://oauth2.googleapis.com/revoke"
_KALENDER_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def _flow(autogenerate_verifier: bool) -> object:
    """Erzeugt den OAuth-Ablauf aus den Zugangsdaten in der .env."""
    from google_auth_oauthlib.flow import Flow

    cfg = current_app.config
    client_config = {
        "web": {
            "client_id": cfg["GOOGLE_OAUTH_CLIENT_ID"],
            "client_secret": cfg["GOOGLE_OAUTH_CLIENT_SECRET"],
            "auth_uri": _AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [cfg["GOOGLE_OAUTH_REDIRECT_URI"]],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=OAUTH_SCOPES,
        redirect_uri=cfg["GOOGLE_OAUTH_REDIRECT_URI"],
        autogenerate_code_verifier=autogenerate_verifier,
    )


class GoogleOAuthService:
    """Verbinden, Trennen und Status der Google-Verbindung."""

    @staticmethod
    def konfiguriert() -> bool:
        """Sind OAuth-Client-ID und -Secret in der .env gesetzt?"""
        cfg = current_app.config
        return bool(cfg.get("GOOGLE_OAUTH_CLIENT_ID") and cfg.get("GOOGLE_OAUTH_CLIENT_SECRET"))

    @staticmethod
    def aktuelle_verbindung() -> GoogleConnection | None:
        return GoogleConnection.query.order_by(GoogleConnection.id.desc()).first()

    @staticmethod
    def status() -> dict:
        """Status für die Oberfläche (ohne jegliche Token-Daten!)."""
        verbindung = GoogleOAuthService.aktuelle_verbindung()
        return {
            "configured": GoogleOAuthService.konfiguriert(),
            "connected": verbindung is not None,
            "account_email": verbindung.account_email if verbindung else None,
            "connected_at": isoformat_utc(verbindung.connected_at) if verbindung else None,
            "connected_by": (
                verbindung.connected_by.full_name
                if verbindung and verbindung.connected_by
                else None
            ),
        }

    @staticmethod
    def start(actor: User) -> tuple[str | None, str | None]:
        """Erzeugt die Google-Anmelde-URL. Rückgabe: (url, fehlertext)."""
        if not GoogleOAuthService.konfiguriert():
            return None, (
                "Google-Anbindung ist noch nicht eingerichtet – GOOGLE_OAUTH_CLIENT_ID und "
                "GOOGLE_OAUTH_CLIENT_SECRET fehlen in der .env (siehe README)."
            )
        flow = _flow(autogenerate_verifier=True)
        url, state = flow.authorization_url(
            access_type="offline",  # -> Google liefert ein Refresh-Token
            prompt="consent",  # -> auch bei erneutem Verbinden ein NEUES Refresh-Token
            include_granted_scopes="true",
        )
        session.permanent = True  # Lebensdauer: PERMANENT_SESSION_LIFETIME (15 min)
        session[_SESSION_KEY] = {
            "state": state,
            "verifier": flow.code_verifier,
            "user_id": actor.id,
        }
        return url, None

    @staticmethod
    def callback(params: dict) -> tuple[bool, str]:
        """Verarbeitet die Rückkehr von Google. Rückgabe: (erfolg, deutsche Meldung)."""
        gemerkt = session.pop(_SESSION_KEY, None)
        if params.get("error"):
            return False, "Die Anmeldung bei Google wurde abgebrochen."
        state = params.get("state") or ""
        if not gemerkt or not secrets.compare_digest(str(gemerkt.get("state", "")), state):
            logger.warning("Google-OAuth: ungültiger oder abgelaufener state")
            return False, "Die Anmeldung ist abgelaufen oder ungültig. Bitte erneut verbinden."
        code = params.get("code")
        if not code:
            return False, "Google hat keinen Anmeldecode geliefert."

        actor = db.session.get(User, gemerkt.get("user_id"))
        if (
            not actor
            or not actor.is_active
            or actor.role.name not in {RoleEnum.CEO.value, RoleEnum.ADMIN.value}
        ):
            return False, "Nur CEO oder Admin dürfen ein Google-Konto verbinden."

        flow = _flow(autogenerate_verifier=False)
        flow.code_verifier = gemerkt.get("verifier")
        # Google meldet die gewährten Berechtigungen teils in anderer Reihenfolge oder mit
        # Zusätzen ("openid") – ohne diese Option würde oauthlib das als Fehler werten.
        os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
        try:
            flow.fetch_token(code=code)
        except Exception:  # noqa: BLE001 - jede Störung beim Token-Tausch gleich behandeln
            logger.exception("Google-OAuth: Token-Tausch fehlgeschlagen")
            return False, "Google hat die Anmeldung nicht bestätigt. Bitte erneut versuchen."

        creds = flow.credentials
        if not creds.refresh_token:
            return False, (
                "Google hat keinen dauerhaften Zugang geliefert. Entferne den Zugriff unter "
                "myaccount.google.com/permissions und verbinde erneut."
            )
        gewaehrt = set(getattr(creds, "granted_scopes", None) or creds.scopes or [])
        if _KALENDER_SCOPE not in gewaehrt:
            return False, "Die Berechtigung für Google Kalender wurde nicht erteilt."

        email = GoogleOAuthService._kontoadresse(creds.token)
        GoogleConnection.query.delete()  # es gibt immer nur EINE Verbindung
        db.session.add(
            GoogleConnection(
                account_email=email,
                refresh_token_enc=encrypt_text(creds.refresh_token),
                scopes=" ".join(sorted(gewaehrt)),
                connected_by_id=actor.id,
            )
        )
        db.session.add(
            AuditLog(
                user_id=actor.id, action="GOOGLE_CONNECTED", details_json={"account_email": email}
            )
        )
        db.session.commit()
        cache_leeren()
        return True, f"Google-Konto {email or ''} verbunden.".replace("  ", " ")

    @staticmethod
    def _kontoadresse(access_token: str | None) -> str | None:
        """E-Mail des verbundenen Google-Kontos (nur zur Anzeige)."""
        if not access_token:
            return None
        try:
            antwort = requests.get(
                _USERINFO_URI, headers={"Authorization": f"Bearer {access_token}"}, timeout=10
            )
            antwort.raise_for_status()
            return antwort.json().get("email")
        except requests.RequestException:
            logger.warning("Google-Kontoadresse konnte nicht ermittelt werden", exc_info=True)
            return None

    @staticmethod
    def trennen(actor: User) -> None:
        """Widerruft den Zugang bei Google und löscht die gespeicherte Verbindung."""
        verbindung = GoogleOAuthService.aktuelle_verbindung()
        if verbindung is None:
            return
        refresh_token = decrypt_text(verbindung.refresh_token_enc)
        if refresh_token:
            try:
                # Widerruf bei Google: danach ist das Token auch für Kopien wertlos.
                requests.post(_REVOKE_URI, params={"token": refresh_token}, timeout=10)
            except requests.RequestException:
                logger.warning("Widerruf des Google-Tokens fehlgeschlagen", exc_info=True)
        email = verbindung.account_email
        GoogleConnection.query.delete()
        db.session.add(
            AuditLog(
                user_id=actor.id,
                action="GOOGLE_DISCONNECTED",
                details_json={"account_email": email},
            )
        )
        db.session.commit()
        cache_leeren()
