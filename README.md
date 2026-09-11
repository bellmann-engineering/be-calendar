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