**Bellmann Calendar System**

Kalender-Managementsystem.

**Voraussetzungen**
1. Docker und Docker Compose sind installiert.

**Installationsanleitung**

1. **Umgebung konfigurieren:**
   in `.env`: Passe die Datenbankvariablen, die Administrator-Anmeldeinformationen an.

2. **Container starten:**
   Erstelle und starte die Datenbank, das Flask-Backend und den Nginx-Server mit folgendem Befehl:
   `docker compose up -d --build`

3. **Datenbank und Testdaten initialisieren:**
   Sobald die Container laufen, führe die Migrationen und Seed-Skripte aus, um die Rollen und Qualifikationen zu laden:
   `docker exec -it bellmann_web flask db upgrade`
   `docker exec -it bellmann_web python seed.py`
   `docker exec -it bellmann_web python seed_dev.py`
   `docker exec -it bellmann_web python create_skills.py`

4. **Systemzugriff:**
   Öffne deinen Webbrowser und rufe `http://localhost:8080` auf.