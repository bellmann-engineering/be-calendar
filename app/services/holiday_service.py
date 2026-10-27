"""
Feiertage für den Kalender – Quelle ist der Urlaubsplaner.

Warum?
    Der Urlaubsplaner pflegt gesetzliche Feiertage (Bayern) und betriebliche freie Tage.
    Der Kalender zeigt dieselben Tage an, ohne eine eigene Liste zu führen: Er fragt
    ``GET <URLAUBSPLANER_HOLIDAYS_URL>?start=…&end=…`` (Header ``X-API-Key``) direkt im
    Docker-Netzwerk ab.

Wie?
    Je Kalenderjahr ein Abruf, im Prozess zwischengespeichert (HOLIDAY_CACHE_SECONDS).
    Ist der Urlaubsplaner nicht erreichbar, gilt der letzte bekannte Stand weiter; nur
    wenn es noch keinen gibt, bleibt die Liste leer und ``error`` ist gesetzt.

Wer ruft das auf?
    ``app/routes/holiday_routes.py`` (GET /api/v1/holidays für das Frontend).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date

import requests
from flask import current_app

logger = logging.getLogger(__name__)

_cache: dict[int, tuple[float, list[dict]]] = {}
_lock = threading.Lock()
TIMEOUT_SECONDS = 4
UNAVAILABLE = "Feiertage aus dem Urlaubsplaner sind gerade nicht abrufbar."


def holidays_enabled() -> bool:
    config = current_app.config
    return bool(config.get("URLAUBSPLANER_HOLIDAYS_URL") and config.get("URLAUBSPLANER_API_KEY"))


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _fetch_year(year: int) -> list[dict]:
    config = current_app.config
    response = requests.get(
        config["URLAUBSPLANER_HOLIDAYS_URL"],
        params={"start": f"{year}-01-01", "end": f"{year}-12-31"},
        headers={"X-API-Key": config["URLAUBSPLANER_API_KEY"], "Accept": "application/json"},
        timeout=TIMEOUT_SECONDS,
        allow_redirects=False,
    )
    response.raise_for_status()
    rows = []
    for item in response.json().get("holidays", []):
        day = date.fromisoformat(item["date"])
        name = str(item["name"]).strip()
        if day.year == year and name:
            rows.append({"date": day, "name": name, "source": str(item.get("source", ""))})
    return rows


def _year(year: int) -> tuple[list[dict], bool]:
    """Feiertage eines Jahres und ob sie (aktuell oder als letzter Stand) vorliegen."""
    max_age = current_app.config.get("HOLIDAY_CACHE_SECONDS", 3600)
    with _lock:
        cached = _cache.get(year)
    if cached and time.monotonic() - cached[0] < max_age:
        return cached[1], True
    try:
        rows = _fetch_year(year)
    except Exception as error:  # Netzwerk, HTTP-Status, ungültiges JSON
        logger.warning("Feiertage %s nicht abrufbar (%s)", year, type(error).__name__)
        return (cached[1], True) if cached else ([], False)
    with _lock:
        _cache[year] = (time.monotonic(), rows)
    return rows, True


def holidays_between(first: date, last: date) -> tuple[list[dict], str | None]:
    """Feiertage von ``first`` bis ``last`` (beide inklusive) und ggf. ein Hinweistext."""
    if not holidays_enabled() or last < first:
        return [], None
    rows, missing = [], False
    for year in range(first.year, last.year + 1):
        year_rows, ok = _year(year)
        missing |= not ok
        rows.extend(row for row in year_rows if first <= row["date"] <= last)
    rows.sort(key=lambda row: (row["date"], row["name"]))
    return rows, UNAVAILABLE if missing else None
