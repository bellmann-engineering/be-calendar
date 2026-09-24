# syntax=docker/dockerfile:1
# =============================================================================
# Dockerfile – Image für den Web-Service "web" (Flask + Gunicorn)
# -----------------------------------------------------------------------------
# Multi-Stage-Build:
#   Stufe 1 "builder": lädt/baut alle Python-Pakete als Wheels.
#   Stufe 2 "runtime": installiert nur die fertigen Wheels + den App-Code.
#   -> Build-Werkzeuge und Caches landen NICHT im finalen Image (kleiner, sicherer).
#
# Zu gcc: Alle Abhängigkeiten gibt es als fertige Wheels (psycopg[binary] bringt
# libpq mit). Ein Compiler wird daher gar nicht benötigt – auch nicht im Builder.
# Sollte künftig ein Paket kompiliert werden müssen, gehört
#   RUN apt-get update && apt-get install -y --no-install-recommends build-essential
# AUSSCHLIESSLICH in die builder-Stufe.
#
# Gestartet wird das Image von docker-compose.yml (Service "web").
# =============================================================================

# ---------------------------------------------------------------- Stufe 1: builder
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
# Nur die Laufzeit-Abhängigkeiten (requirements-dev.txt bleibt draußen).
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ---------------------------------------------------------------- Stufe 2: runtime
FROM python:3.12-slim AS runtime

# PYTHONDONTWRITEBYTECODE: keine .pyc-Dateien (Code-Verzeichnis ist read-only)
# PYTHONUNBUFFERED:        Logs sofort an stdout -> "docker compose logs" zeigt sie live
# APP_ENV=production:      Standard im Container; aktiviert ProductionConfig (DEBUG aus)
# FLASK_APP:               für "flask db upgrade" im Entrypoint
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production \
    FLASK_APP=wsgi.py

# Eigener, unprivilegierter Benutzer: Selbst bei einer Lücke in der App hat ein
# Angreifer im Container keine Root-Rechte.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/* && rm -rf /wheels

# App-Code gehört root und ist für "app" nur lesbar (kein Überschreiben des eigenen Codes).
COPY . .
RUN chmod 0755 docker-entrypoint.sh

USER app

EXPOSE 5000

# Docker prüft alle 30 s, ob die App (inkl. DB-Verbindung) antwortet.
# Python statt curl, weil das slim-Image kein curl enthält.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=4).status == 200 else 1)"

# Entrypoint führt zuerst die DB-Migrationen aus, dann das CMD (Gunicorn).
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
