# Bellmann Calendar System

Ein professionelles Kalender-Managementsystem für Bellmann Engineering (Clean Architecture).

## Voraussetzungen
1. **Git** ist auf dem System installiert.
2. **Docker Desktop** (inkl. Docker Compose) ist installiert und läuft im Hintergrund.

## 🚀 Schnellstart (Automatische Installation)

Am einfachsten lässt sich das Projekt über das beiliegende Setup-Skript starten. Es erstellt automatisch die benötigte sichere `.env`-Datei, startet die Docker-Container und befüllt die Datenbank mit den initialen Systemrollen, Qualifikationen und dem Admin-Zugang.

**Im Terminal ausführen:**
```bash
# 1. Skript ausführbar machen (nur Mac/Linux nötig)
chmod +x setup.sh

# 2. Automatisches Setup starten
./setup.sh

=====================================================================================================================================================
=====================================================================================================================================================

🛠 Manuelle Installation (Alternativ)
Falls das Setup-Skript in deiner Umgebung nicht ausgeführt werden kann, kannst du das System manuell starten:

Umgebung konfigurieren:
Erstelle eine Datei namens .env im Hauptverzeichnis (die Vorlage für die benötigten Variablen findest du im setup.sh Skript).

Docker Container starten:

Bash
docker compose up -d --build
Datenbank initialisieren:
Sobald die Container laufen, führe nacheinander diese Befehle aus:

Bash
docker exec -it bellmann_web flask db upgrade
docker exec -it bellmann_web python seed.py
docker exec -it bellmann_web python seed_dev.py
docker exec -it bellmann_web python create_skills.py