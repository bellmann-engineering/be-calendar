#!/usr/bin/env bash
# =============================================================================
# backup_db.sh – Sicherung der PostgreSQL-Datenbank aus dem Container "bellmann_db"
# -----------------------------------------------------------------------------
# Wann?   IMMER vor Updates/Migrationen (rebuild, "flask db upgrade") und regelmäßig
#         (z. B. täglich per Cron).
# Wohin?  $BACKUP_DIR (Standard: ~/bellmann-backups) – bewusst AUSSERHALB des Projekts,
#         damit Sicherungen nie versehentlich in Git oder einem Code-Export landen.
# Format: pg_dump "custom" (-Fc): komprimiert, einzelne Tabellen wiederherstellbar.
#
# Wiederherstellen (überschreibt die aktuelle DB!):
#   docker exec -i bellmann_db sh -c 'pg_restore --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < DATEI.dump
#
# Aufruf:  ./scripts/backup_db.sh [kennzeichnung]      z. B. ./scripts/backup_db.sh vor-update
# Alte Sicherungen: Es werden die letzten $KEEP (Standard 20) Dateien behalten.
# =============================================================================
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/bellmann-backups}"
KEEP="${KEEP:-20}"
LABEL="${1:-manuell}"
CONTAINER="${DB_CONTAINER:-bellmann_db}"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"   # Dumps enthalten Passwort-Hashes -> nur für den Besitzer

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "!! Container $CONTAINER läuft nicht – keine Sicherung möglich." >&2
    exit 1
fi

FILE="$BACKUP_DIR/bellmann_$(date +%Y%m%d-%H%M%S)_${LABEL}.dump"
# Die Variablen in einfachen Anführungszeichen werden IM Container ausgewertet.
docker exec "$CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$FILE"
chmod 600 "$FILE"

# Plausibilitätsprüfung: Kann pg_restore das Inhaltsverzeichnis lesen?
if ! docker exec -i "$CONTAINER" pg_restore --list < "$FILE" > /dev/null; then
    echo "!! Sicherung $FILE ist beschädigt!" >&2
    exit 1
fi
echo "Sicherung erstellt: $FILE ($(du -h "$FILE" | cut -f1))"

# Rotation: nur die neuesten $KEEP Sicherungen behalten.
ls -1t "$BACKUP_DIR"/bellmann_*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
