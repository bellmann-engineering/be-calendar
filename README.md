# Bellmann Calendar System

Kalender- und Einsatzplanung für **Bellmann Engineering**: Termine anlegen und Mitarbeitern zuweisen, Rückmeldungen (RSVP) mit Pflichtbegründung, automatische Kollisionserkennung inkl. Pufferzeiten und privatem Google-Kalender, Rollen- und Teamrechte sowie ein lückenloses Audit-Log.

## Architektur

```
Browser ──:8080──> Nginx ──:5000──> Gunicorn (gthread) ──> Flask-App ──> PostgreSQL 16
                    │                                         ├──> SMTP (E-Mails, nach Commit)
                    └ Security-Header, Rate-Limit             └──> Google Calendar API (optional)
```

| Schicht | Ordner | Aufgabe |
|---|---|---|
| Routen | `app/routes/` | HTTP rein/raus, JSON, `@jwt_required`, `@role_required` |
| Services | `app/services/` | Geschäftsregeln, Validierung, Transaktionen |
| Models | `app/models/` | Tabellen (SQLAlchemy), Beziehungen, Indizes |
| Frontend | `app/templates/`, `app/static/js/app.js` | Jinja2-Seiten + FullCalendar, spricht nur mit `/api/v1/...` |
| Migrationen | `migrations/` | Alembic – **einzige** Quelle für Schemaänderungen |

**Rollen:** CEO > ADMIN > TEAM_LEADER > TRAINER (Regeln in `app/services/authorization_service.py`).

**Sitzung:** JWT in HttpOnly-Cookies (Access 30 min, Refresh 8 h) mit CSRF-Double-Submit. JavaScript kann das Token nicht lesen.

## 🚀 Schnellstart (Docker)

Voraussetzungen: Git, Docker Desktop (inkl. Compose).

```bash
chmod +x setup.sh
./setup.sh
```

Das Skript erzeugt eine `.env` mit **zufälligen** Secrets, baut und startet die Container (Migrationen laufen automatisch), legt die Rollen und einen CEO-Zugang an. Login-Daten: `DEV_USER_EMAIL` / `DEV_USER_PASSWORD` in der `.env`.

Optional Google Calendar: Service-Account-Datei nach `secrets/google_credentials.json` legen.

## Lokale Entwicklung (ohne Docker für die App)

```bash
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install                    # ruff + black vor jedem Commit
cp .env.example .env                  # Werte anpassen
flask db upgrade && python seed.py && python seed_dev.py
python run.py                         # http://127.0.0.1:5000
```

Datenbank lokal erreichbar machen: `docker-compose.override.yml` mit `ports: ["127.0.0.1:5432:5432"]` für den Service `db` anlegen (siehe Kommentar in `docker-compose.yml`).

## Tests & Code-Qualität

```bash
export TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/bellmann_test   # wird geleert!
pytest --cov              # baut das Schema über alle Migrationen auf und testet die API
ruff check . && black --check .
```

Die CI (`.github/workflows/ci.yml`) führt `lint → test → build → push (GHCR)` aus. PR-Titel müssen den [Conventional Commits](https://www.conventionalcommits.org/de/) folgen (`feat: …`, `fix: …`).

## Datenbank-Migrationen

```bash
flask db migrate -m "beschreibung"   # neue Migration aus den Model-Änderungen erzeugen
flask db upgrade                     # anwenden (im Container automatisch beim Start)
flask db check                       # prüft, ob Models und Datenbank übereinstimmen
```

`db.create_all()` wird **nie** verwendet. Vor Upgrades in Produktion: `docker compose exec db pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup.sql`.

**Bestehende Installation, deren `alembic_version` auf eine gelöschte Skills-Migration zeigt** (z. B. `e1f2a3b4c5d6`): einmalig `flask db stamp bcf52e20a906`, danach `flask db upgrade`. Die Migration `a7c9e2d4f6b8` ist idempotent und ergänzt nur, was fehlt.

## Betrieb

| Thema | Ort |
|---|---|
| Worker/Threads, Timeouts | `gunicorn.conf.py` (Env: `GUNICORN_WORKERS`, `GUNICORN_THREADS`) |
| Security-Header, CSP, Rate-Limit | `nginx/nginx.conf` |
| Alle Einstellungen | `app/config.py`, Vorlage `.env.example` |
| Logs (JSON) | `docker compose logs -f web` |
| Health-Check | `GET /health` (prüft auch die DB) |

HTTPS: Zertifikat in Nginx einbinden, danach `COOKIE_SECURE=1` setzen und die HSTS-Zeile in `nginx.conf` aktivieren.
