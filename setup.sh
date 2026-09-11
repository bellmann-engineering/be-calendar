#!/bin/bash

echo " Starte Bellmann Calendar Setup..."

# 1. Prüfen, ob die .env Datei existiert, falls nicht -> automatisch anlegen
if [ ! -f .env ]; then
    echo " Keine .env Datei gefunden. Erstelle Standard-Konfiguration..."
    cat << 'EOF' > .env
# --- Flask-Konfiguration ---
FLASK_APP=run.py
FLASK_ENV=development
FLASK_DEBUG=1
SECRET_KEY=***ENTFERNT***

# --- Datenbank-Konfiguration (PostgreSQL) ---
POSTGRES_USER=bellmann_user
POSTGRES_PASSWORD=***ENTFERNT***
POSTGRES_DB=bellmann_calendar_db
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
DATABASE_URL=***ENTFERNT***

# --- Sicherheit & JWT Token ---
JWT_SECRET_KEY=***ENTFERNT***

# --- Dev / Admin Account credentials ---
DEV_USER_EMAIL=dev@bellmann-engineering.com
DEV_USER_PASSWORD=***ENTFERNT***
EOF
    echo " .env Datei erfolgreich erstellt."
else
    echo " .env Datei existiert bereits."
fi

# 2. Docker Container bauen und starten
echo "... Starte Docker Container..."
docker compose up -d --build

# 3. Kurz warten, damit die Datenbank hochfahren kann
echo "... Warte 5 Sekunden, bis die Datenbank bereit ist..."
sleep 5

# 4. Datenbank initialisieren und Seed-Daten laden
echo " Initialisiere Datenbank und lade Testdaten..."
docker exec -it bellmann_web flask db upgrade
docker exec -it bellmann_web python seed.py
docker exec -it bellmann_web python seed_dev.py
docker exec -it bellmann_web python create_skills.py

# 5. Abschlussmeldung
echo ""
echo " SETUP ABGESCHLOSSEN! "
echo "======================================================="
echo "Das Kalendersystem ist nun live."
echo "Öffne deinen Browser unter: http://localhost:8080"
echo ""
echo "Login-Daten:"
echo "E-Mail:    dev@bellmann-engineering.com"
echo "Passwort:  ***ENTFERNT***
echo "======================================================="