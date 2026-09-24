#!/bin/sh
# =============================================================================
# docker-entrypoint.sh – Startskript des Web-Containers
# -----------------------------------------------------------------------------
# 1. Wendet ausstehende Datenbank-Migrationen an ("flask db upgrade", Alembic).
#    Abschaltbar mit RUN_MIGRATIONS=0 (z. B. bei mehreren Web-Instanzen, damit
#    nicht mehrere Container gleichzeitig migrieren).
# 2. Startet danach das eigentliche Kommando aus dem Dockerfile (CMD = Gunicorn).
#    "exec" ersetzt die Shell durch Gunicorn -> Gunicorn ist PID 1 und bekommt
#    Signale wie SIGTERM (docker stop) direkt und kann sauber herunterfahren.
# =============================================================================
set -eu

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    echo "[entrypoint] Wende Datenbank-Migrationen an ..."
    flask db upgrade
fi

exec "$@"
