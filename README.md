# Bellmann Calendar System

Kalender- und Einsatzplanung für **Bellmann Engineering**: Termine anlegen und Mitarbeitern zuweisen, Rückmeldungen (RSVP) mit Pflichtbegründung, automatische Kollisionserkennung inkl. Pufferzeiten und privatem Google-Kalender, Rollen- und Teamrechte sowie ein lückenloses Audit-Log.

> **⚠️ Wichtiger Hinweis (24.09.2026): Der Git-Verlauf wurde bereinigt.**
> Alte Commits enthielten Zugangsdaten (`.env`, Passwörter in `setup.sh`). Der Verlauf wurde neu geschrieben und alle betroffenen Secrets wurden rotiert.
> Wer das Repository vor diesem Datum geklont hat, muss es **neu klonen** oder im Projektordner ausführen:
> ```bash
> git stash            # nur falls lokale, nicht committete Änderungen vorhanden sind
> git fetch && git reset --hard origin/main
> git stash pop        # lokale Änderungen zurückholen (falls vorher gestasht)
> ```
> Bitte **nicht** den alten Stand pushen – sonst landen die alten Commits wieder auf GitHub.

---

## Inhalt

1. [Architektur](#architektur)
2. [Schnellstart (Docker)](#schnellstart-docker)
3. [Updates einspielen](#updates-einspielen)
4. [Konfiguration (.env)](#konfiguration-env)
5. [E-Mail-Versand (SMTP)](#e-mail-versand-smtp)
6. [HTTPS und Zertifikate](#https-und-zertifikate)
7. [Datensicherung und Wiederherstellung](#datensicherung-und-wiederherstellung)
8. [Lokale Entwicklung](#lokale-entwicklung)
9. [Tests und Code-Qualität](#tests-und-code-qualität)
10. [Datenbank-Migrationen](#datenbank-migrationen)
11. [Rollen und Berechtigungen](#rollen-und-berechtigungen)
12. [Sicherheit](#sicherheit)
13. [Projektregeln](#projektregeln)
14. [Fehlerbehebung](#fehlerbehebung)

---

## Architektur

```
Browser ──https:8443──> Nginx ──:5000──> Gunicorn (gthread) ──> Flask-App ──> PostgreSQL 16
          (http:8080 leitet  │                                     ├──> SMTP (E-Mails, nach dem Commit)
           auf https um)     └ TLS, Security-Header, Rate-Limit    └──> Google Calendar API (optional)
```

Alle drei Dienste laufen als Docker-Container (`docker-compose.yml`). Von außen erreichbar ist **nur Nginx**; Web-App und Datenbank hängen ausschließlich im internen Docker-Netzwerk.

| Schicht | Ordner | Aufgabe |
|---|---|---|
| Routen | `app/routes/` | HTTP rein/raus, JSON, `@jwt_required`, `@role_required` |
| Services | `app/services/` | Geschäftsregeln, Validierung, Transaktionen |
| Models | `app/models/` | Tabellen (SQLAlchemy), Beziehungen, Indizes |
| Frontend | `app/templates/`, `app/static/js/app.js` | Jinja2-Seiten + FullCalendar, spricht nur mit `/api/v1/...` |
| Migrationen | `migrations/` | Alembic – **einzige** Quelle für Schemaänderungen |
| Infrastruktur | `Dockerfile`, `gunicorn.conf.py`, `nginx/`, `scripts/` | Image, WSGI-Server, Reverse Proxy, Betriebsskripte |

**Sitzung:** JWT in HttpOnly-Cookies (Access 30 min, Refresh 8 h) mit CSRF-Double-Submit. JavaScript kann das Token nicht lesen.

---

## Schnellstart (Docker)

**Voraussetzungen:** Git, Docker Desktop (inkl. Compose; unter Windows mit aktivierter WSL-Integration).

```bash
git clone https://github.com/bellmann-engineering/be-calendar.git
cd be-calendar
chmod +x setup.sh scripts/*.sh
./setup.sh
```

Das Skript
1. erzeugt eine `.env` mit **zufälligen** Secrets (falls noch keine existiert),
2. erzeugt ein selbstsigniertes TLS-Zertifikat (`scripts/generate_dev_cert.sh`),
3. baut und startet die Container – die Datenbank-Migrationen laufen dabei automatisch,
4. legt die Rollen und einen CEO-Zugang an.

Danach im Browser öffnen: **https://localhost:8443**
Die Zertifikatswarnung des Browsers einmalig bestätigen (selbstsigniertes Zertifikat, siehe [HTTPS](#https-und-zertifikate)).
Login-Daten: `DEV_USER_EMAIL` / `DEV_USER_PASSWORD` aus der `.env` – das Passwort nach dem ersten Login ändern.

Optional Google Calendar: Service-Account-Datei als `secrets/google_credentials.json` ablegen (wird read-only in den Container eingehängt).

---

## Updates einspielen

```bash
git pull
./scripts/backup_db.sh vor-update      # Sicherung der Datenbank (siehe unten)
docker compose up -d --build           # neues Image bauen, Container neu starten
docker compose ps                      # "web" muss nach kurzer Zeit "healthy" sein
```

Neue Migrationen werden beim Start des Web-Containers automatisch angewendet (`docker-entrypoint.sh`).

---

## Konfiguration (.env)

Alle Einstellungen kommen aus der Datei `.env` (nicht in Git). Die Vorlage mit Erklärung jeder Variable ist **`.env.example`**; die Auswertung passiert in `app/config.py`.

| Variable | Bedeutung |
|---|---|
| `SECRET_KEY`, `JWT_SECRET_KEY` | Pflicht, je mind. 32 Zeichen. Ohne sie startet die App in Produktion nicht. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Zugang zur Datenbank |
| `APP_BASE_URL` | Öffentliche Adresse (für Links in E-Mails), z. B. `https://localhost:8443` |
| `COOKIE_SECURE` | `1` = Cookies nur über HTTPS (Standard). Nur für `python run.py` ohne TLS auf `0`. |
| `HTTP_PORT`, `HTTPS_PORT` | Öffentliche Ports von Nginx (Standard 8080 / 8443) |
| `SMTP_*`, `MAIL_DEFAULT_SENDER` | E-Mail-Versand, siehe unten |
| `DEV_USER_EMAIL`, `DEV_USER_PASSWORD` | Erster CEO-Zugang (`seed_dev.py`) |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS` | Dimensionierung des WSGI-Servers (`gunicorn.conf.py`) |

Neues Secret erzeugen: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

---

## E-Mail-Versand (SMTP)

Ohne SMTP-Konfiguration läuft die App normal, verschickt aber **keine E-Mails**. Betroffen sind:
- „Passwort vergessen“ (Link zum Zurücksetzen),
- Einladungen nach dem CSV-Import (Link zum Festlegen des Passworts),
- Benachrichtigungen bei Terminzuweisung und -ablehnung.

In der `.env` eintragen und danach `docker compose up -d` ausführen:
```
SMTP_SERVER=smtp.beispiel.de
SMTP_PORT=587
SMTP_USER=kalender@bellmann-engineering.com
SMTP_PASSWORD=...
MAIL_DEFAULT_SENDER=kalender@bellmann-engineering.com
```
Der Versand erfolgt per STARTTLS, im Hintergrund und erst **nach** dem erfolgreichen Speichern in der Datenbank. Fehler stehen im Log: `docker compose logs web | grep -i mail`.

---

## HTTPS und Zertifikate

Nginx liefert die Anwendung ausschließlich über HTTPS aus (TLS 1.2/1.3). Aufrufe über `http://…:8080` werden dauerhaft auf `https://…:8443` umgeleitet.

- **Lokal / Intranet:** `scripts/generate_dev_cert.sh` erzeugt ein selbstsigniertes Zertifikat unter `nginx/certs/` (nicht in Git). Für den Zugriff über eine IP-Adresse im Büronetz:
  `./scripts/generate_dev_cert.sh --force 192.168.1.50`
- **Produktion mit eigener Domain:** ein echtes Zertifikat (z. B. Let's Encrypt) als `nginx/certs/fullchain.pem` und `nginx/certs/privkey.pem` ablegen und `APP_BASE_URL` auf die Domain setzen. HSTS wird für echte Domains automatisch gesendet (für `localhost` bewusst nicht).

---

## Datensicherung und Wiederherstellung

```bash
./scripts/backup_db.sh [kennzeichnung]
```
Sicherungen landen in `~/bellmann-backups/` (bewusst außerhalb des Projekts, Rechte 600). Die letzten 20 werden behalten.

**Wiederherstellen** (überschreibt die aktuelle Datenbank!):
```bash
docker exec -i bellmann_db sh -c 'pg_restore --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < ~/bellmann-backups/DATEI.dump
```

---

## Lokale Entwicklung

```bash
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install                    # ruff + black vor jedem Commit
cp .env.example .env                  # Werte anpassen, für run.py ohne TLS: COOKIE_SECURE=0
flask db upgrade && python seed.py && python seed_dev.py
python run.py                         # http://127.0.0.1:5000
```

Für den Zugriff auf die Docker-Datenbank vom eigenen Rechner (z. B. mit DBeaver) eine Datei `docker-compose.override.yml` anlegen (wird von Git ignoriert):
```yaml
services:
  db:
    ports: ["127.0.0.1:5432:5432"]
```

---

## Tests und Code-Qualität

Die Tests benötigen eine **eigene** PostgreSQL-Datenbank, die bei jedem Lauf geleert wird. Am einfachsten per Docker:
```bash
docker run -d --rm --name bellmann_test_pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=bellmann_test \
  -p 127.0.0.1:55433:5432 --tmpfs /var/lib/postgresql/data postgres:16-alpine
export TEST_DATABASE_URL=postgresql+psycopg://postgres:test@127.0.0.1:55433/bellmann_test
pytest --cov                          # baut das Schema über alle Migrationen auf und testet die API
ruff check . && black --check .
docker rm -f bellmann_test_pg         # Test-Datenbank wieder entfernen
```

Die CI (`.github/workflows/ci.yml`) führt bei jedem Push `lint → test → build → push (GHCR)` aus; die Testabdeckung muss mindestens 70 % betragen. PR-Titel müssen den [Conventional Commits](https://www.conventionalcommits.org/de/) folgen (`feat: …`, `fix: …`, `docs: …`).

---

## Datenbank-Migrationen

```bash
flask db migrate -m "beschreibung"   # neue Migration aus den Model-Änderungen erzeugen – danach prüfen!
flask db upgrade                     # anwenden (im Container automatisch beim Start)
flask db check                       # prüft, ob Models und Datenbank übereinstimmen
```
Im Container: `docker exec bellmann_web flask db check`.

**Bestehende Installation, deren `alembic_version` auf eine gelöschte Skills-Migration zeigt** (z. B. `e1f2a3b4c5d6` oder `b0287b7f27b8`): vorher sichern, dann einmalig `flask db stamp bcf52e20a906` und danach `flask db upgrade`. Die Migration `a7c9e2d4f6b8` ist idempotent und ergänzt nur, was fehlt.

---

## Rollen und Berechtigungen

| Rolle | Darf |
|---|---|
| **CEO** | alles, inkl. Terminüberbuchung (`override_conflict=true`) und Anlegen von Admins |
| **ADMIN** | Benutzer (nur TRAINER/TEAM_LEADER), Kunden, alle Termine, Audit-Log |
| **TEAM_LEADER** | Termine für Mitglieder des **eigenen** Teams anlegen, ändern, neu zuweisen |
| **TRAINER** | eigene Termine sehen und Einladungen bestätigen/ablehnen (Ablehnung mit Begründung) |

Die Regeln stehen zentral in `app/services/authorization_service.py`. Rechteänderungen und Deaktivierungen wirken **sofort**, weil die Rolle bei jedem Request aus der Datenbank gelesen wird.

---

## Sicherheit

- Tokens nur in HttpOnly/Secure/SameSite=Strict-Cookies, CSRF-Schutz für alle schreibenden Anfragen.
- Alle Benutzereingaben werden im Frontend escaped (`escapeHtml` / `textContent`), zusätzlich Content-Security-Policy in Nginx.
- Brute-Force-Schutz für Login und Passwort-Reset (Nginx `limit_req` + Flask-Limiter).
- Passwort-Reset nur über signierte Einmal-Links; es werden nie Passwörter per E-Mail verschickt.
- Keine Fehlerdetails (SQL, Stacktraces) an den Client; vollständige Fehler stehen im JSON-Log.
- Container laufen ohne Root-Rechte; die Datenbank ist von außen nicht erreichbar.
- Bekannte offene Verbesserung: Tailwind wird noch über das Play-CDN geladen, daher benötigt die CSP `'unsafe-inline'` (siehe Kommentar in `app/templates/base.html`).

---

## Projektregeln

- **Sprache:** Code-Kommentare, Meldungen und Dokumentation auf **Deutsch** (Fachbegriffe dürfen Englisch sein).
- **Zeitangaben:** niemals `datetime.utcnow()`, immer `datetime.now(timezone.utc)` bzw. `app.utils.time.utc_now()`. In der Datenbank wird `timestamptz` (UTC) gespeichert.
- **Schemaänderungen:** ausschließlich über Alembic-Migrationen, niemals `db.create_all()`.
- **Zugangsdaten:** nur in der `.env` (nie im Code, in `docker-compose.yml` oder in Git).
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `build:`, `test:`, `ci:`, `chore:`), Stil und Linting prüft `pre-commit` automatisch.

---

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| Login klappt nicht, man landet wieder auf `/login` | Aufruf über `https://…:8443`? Bei Zugriff ohne HTTPS muss `COOKIE_SECURE=0` gesetzt sein. |
| Browser meldet „Verbindung nicht sicher“ | Erwartet beim selbstsignierten Zertifikat – einmalig bestätigen oder echtes Zertifikat einbinden. |
| Container `web` wird nicht „healthy“ | `docker compose logs --tail 50 web` – meist fehlende/kurze Secrets in der `.env` oder eine Migration. |
| `Can't locate revision ...` beim Start | siehe [Datenbank-Migrationen](#datenbank-migrationen) (`flask db stamp`). |
| Keine E-Mails | SMTP in der `.env` konfigurieren, siehe [E-Mail-Versand](#e-mail-versand-smtp). |
| Seite zeigt alten Stand | Nach einem Update im Browser `Strg+F5` drücken. |

**Betrieb auf einen Blick**

| Thema | Ort |
|---|---|
| Worker/Threads, Timeouts | `gunicorn.conf.py` |
| Security-Header, CSP, Rate-Limit, TLS | `nginx/nginx.conf` |
| Alle Einstellungen | `app/config.py`, Vorlage `.env.example` |
| Logs (JSON) | `docker compose logs -f web` |
| Health-Check | `GET /health` (prüft auch die Datenbank) |
| Backup / Zertifikat | `scripts/backup_db.sh`, `scripts/generate_dev_cert.sh` |
