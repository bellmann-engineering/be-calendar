#!/usr/bin/env bash
# =============================================================================
# setup.sh – Ersteinrichtung von Bellmann Calendar mit Docker
# -----------------------------------------------------------------------------
# Was passiert?
#   1. Falls keine .env existiert: .env mit ZUFÄLLIG erzeugten Secrets anlegen.
#      (Früher standen feste Passwörter/Schlüssel hier im Skript – und damit in Git.
#      Jeder mit Repo-Zugriff hätte gültige Login-Tokens fälschen können.)
#   2. TLS-Zertifikat erzeugen (scripts/generate_dev_cert.sh), dann
#      Container bauen und starten (docker compose up -d --build).
#      Die DB-Migrationen laufen automatisch beim Start des Web-Containers
#      (docker-entrypoint.sh -> flask db upgrade).
#   3. Warten, bis der Web-Container "healthy" ist.
#   4. Rollen und den ersten CEO-Zugang anlegen (seed.py, seed_dev.py).
#
# Aufruf:  chmod +x setup.sh && ./setup.sh
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"

# Erzeugt einen kryptografisch zufälligen, URL-sicheren String.
random_secret() {
    python3 -c "import secrets; print(secrets.token_urlsafe($1))" 2>/dev/null \
        || openssl rand -base64 "$1" | tr -d '\n/+='
}

echo "==> Starte Bellmann Calendar Setup ..."

# --------------------------------------------------------------------- 1) .env
if [ ! -f .env ]; then
    echo "==> Keine .env gefunden – erzeuge eine neue mit zufälligen Secrets ..."
    DB_PASSWORD="$(random_secret 24)"
    DEV_PASSWORD="$(random_secret 12)"
    cat > .env <<EOF
# Automatisch erzeugt von setup.sh am $(date -Iseconds). NICHT committen!
# Beschreibung aller Variablen: siehe .env.example

# --- Flask ---
FLASK_APP=wsgi.py
SECRET_KEY=$(random_secret 48)
JWT_SECRET_KEY=$(random_secret 48)
APP_BASE_URL=https://localhost:8443
# 1 = Cookies nur über HTTPS (Nginx terminiert TLS auf Port 8443).
COOKIE_SECURE=1

# --- Datenbank (PostgreSQL) ---
POSTGRES_USER=bellmann_user
POSTGRES_PASSWORD=${DB_PASSWORD}
POSTGRES_DB=bellmann_calendar_db
# Nur für lokales Arbeiten ohne Docker (python run.py). In Docker setzt Compose die URL.
DATABASE_URL=postgresql+psycopg://bellmann_user:${DB_PASSWORD}@localhost:5432/bellmann_calendar_db

# --- Erster CEO-Zugang (seed_dev.py) ---
DEV_USER_EMAIL=dev@bellmann-engineering.com
DEV_USER_PASSWORD=${DEV_PASSWORD}

# --- E-Mail (optional) ---
SMTP_SERVER=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
MAIL_DEFAULT_SENDER=noreply@bellmann-engineering.com
EOF
    chmod 600 .env
    echo "    .env erstellt (Rechte 600 – nur für dich lesbar)."
else
    echo "==> .env existiert bereits – wird nicht verändert."
fi

# TLS-Zertifikat für Nginx (selbstsigniert, falls noch keins existiert).
./scripts/generate_dev_cert.sh

# --------------------------------------------------------------------- 2) Container
echo "==> Baue und starte die Docker-Container ..."
docker compose up -d --build

# --------------------------------------------------------------------- 3) Warten
echo "==> Warte, bis der Web-Container bereit ist (Migrationen laufen) ..."
for _ in $(seq 1 60); do
    status="$(docker inspect -f '{{.State.Health.Status}}' bellmann_web 2>/dev/null || echo starting)"
    if [ "$status" = "healthy" ]; then
        break
    fi
    sleep 2
done
if [ "${status:-}" != "healthy" ]; then
    echo "!! Web-Container wurde nicht rechtzeitig 'healthy'. Logs: docker compose logs web"
    exit 1
fi

# --------------------------------------------------------------------- 4) Seed-Daten
echo "==> Lege Rollen und CEO-Zugang an ..."
docker compose exec -T web python seed.py
docker compose exec -T web python seed_dev.py

DEV_EMAIL="$(grep -E '^DEV_USER_EMAIL=' .env | cut -d= -f2-)"
echo ""
echo "======================================================="
echo " SETUP ABGESCHLOSSEN"
echo "======================================================="
echo " Browser:  https://localhost:8443   (Zertifikatswarnung einmalig bestätigen)"
echo " Login:    ${DEV_EMAIL}"
echo " Passwort: steht in der .env unter DEV_USER_PASSWORD"
echo "           -> nach dem ersten Login bitte ändern!"
echo "======================================================="
