"""
Gunicorn-Konfiguration (WSGI-Server im Docker-Container).

Gelesen von: ``gunicorn --config gunicorn.conf.py wsgi:app`` (CMD im Dockerfile).

Warum ``gthread`` statt ``sync``?
    Die App ist I/O-lastig: Jeder Request wartet überwiegend auf PostgreSQL, teilweise auf
    die Google Calendar API (~0,2–1 s) und – falls nicht asynchron – auf SMTP.
    * ``sync`` mit 3 Workern = höchstens 3 gleichzeitige Requests. Drei langsame
      Google-Aufrufe blockieren die komplette Anwendung.
    * ``gthread`` mit 3 Workern x 4 Threads = 12 gleichzeitige Requests bei nahezu
      gleichem Speicherbedarf (weiterhin 3 Prozesse). Das GIL stört nicht, weil Threads
      beim Warten auf I/O das GIL freigeben.
    * ``gevent``/``eventlet`` wurden bewusst NICHT gewählt: Sie erfordern Monkey-Patching
      von psycopg und httplib2 (Google) – fehleranfällig ohne großen Zusatznutzen hier.

Dimensionierung (per Umgebungsvariablen anpassbar):
    * GUNICORN_WORKERS: Faustregel für I/O-lastige Apps mit Threads: 1–2 pro CPU-Kern.
      Standard 3 passt für einen kleinen Server mit 2 vCPUs.
    * GUNICORN_THREADS: 4. Muss zum DB-Pool passen: pool_size (5) >= Threads (4),
      sonst warten Threads auf freie Verbindungen (siehe app/config.py).
    * Gesamt-DB-Verbindungen: Worker x (pool_size + max_overflow) = 3 x 7 = 21.
"""

import os

# An alle Interfaces im Container binden – erreichbar ist Port 5000 trotzdem nur im
# Docker-Netzwerk (docker-compose: "expose", nicht "ports"). Davor sitzt Nginx.
bind = "0.0.0.0:5000"  # noqa: S104

worker_class = "gthread"
workers = int(os.getenv("GUNICORN_WORKERS", "3"))
threads = int(os.getenv("GUNICORN_THREADS", "4"))

# Nach 60 s ohne Lebenszeichen wird ein Worker neu gestartet (Google-Timeout = 10 s,
# SMTP läuft im Hintergrund-Thread). Nginx wartet etwas länger (proxy_read_timeout 65 s).
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30  # Zeit für laufende Requests beim Herunterfahren (docker stop)
keepalive = 5  # Sekunden, die eine Keep-Alive-Verbindung von Nginx offen bleibt

# Worker nach ~1000 Requests (mit Zufallsstreuung) recyceln: schützt vor schleichenden
# Speicherlecks, ohne dass alle Worker gleichzeitig neu starten.
max_requests = 1000
max_requests_jitter = 100

# Heartbeat-Dateien im RAM statt auf der (evtl. langsamen/read-only) Container-Disk.
worker_tmp_dir = "/dev/shm"  # noqa: S108 - von Gunicorn für Docker empfohlen

# Steuer-Socket (ab Gunicorn 25.1) für das Werkzeug "gunicornc" (Worker anzeigen, Reload).
# Standard wäre ~/.gunicorn/… – der Container-Benutzer "app" hat aber kein Home-
# Verzeichnis (Permission denied). Daher ebenfalls in den RAM legen.
control_socket = "/dev/shm/gunicorn.ctl"  # noqa: S108

# Logs nach stdout/stderr -> von Docker eingesammelt.
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()

# preload_app = False (Standard): Jeder Worker erzeugt nach dem Fork seinen eigenen
# DB-Connection-Pool. Geteilte Sockets zwischen Prozessen würden sonst kaputtgehen.
preload_app = False
