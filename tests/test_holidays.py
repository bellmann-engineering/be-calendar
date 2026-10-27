"""
Tests für die Feiertage aus dem Urlaubsplaner (GET /api/v1/holidays): Abruf je Jahr,
Zwischenspeicher, letzter Stand bei Ausfall, Anmeldepflicht.
"""

import pytest
import requests

from app.services import holiday_service

URL = "http://urlaubsplaner.test/api/v1/holidays"


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.payload


@pytest.fixture()
def upstream(app, monkeypatch):
    """Ersetzt den Urlaubsplaner; calls zählt die Abrufe, rows liefert die Antwort je Jahr."""
    app.config.update(URLAUBSPLANER_HOLIDAYS_URL=URL, URLAUBSPLANER_API_KEY="k" * 40, HOLIDAY_CACHE_SECONDS=3600)
    holiday_service.clear_cache()
    state = {"calls": [], "fail": False}

    def fake_get(url, params, headers, timeout, allow_redirects):
        assert url == URL and headers["X-API-Key"] == "k" * 40 and not allow_redirects
        state["calls"].append(params["start"][:4])
        if state["fail"]:
            raise requests.ConnectionError("down")
        year = params["start"][:4]
        return FakeResponse({"holidays": [
            {"date": f"{year}-12-25", "name": "Erster Weihnachtstag", "source": "Gesetzlich"},
            {"date": f"{year}-12-24", "name": "Heiligabend", "source": "Betrieblich"},
        ]})

    monkeypatch.setattr(holiday_service.requests, "get", fake_get)
    yield state
    holiday_service.clear_cache()
    app.config.update(URLAUBSPLANER_HOLIDAYS_URL="", URLAUBSPLANER_API_KEY="")


def _get(client, start, end):
    return client.get(f"/api/v1/holidays?start={start}&end={end}")


def test_requires_login(client, upstream):
    assert _get(client, "2026-12-01", "2027-01-10").status_code == 401


def test_holidays_across_year_end_end_exclusive(client, login, make_user, upstream):
    login(make_user())
    response = _get(client, "2026-12-24T00:00:00+01:00", "2027-12-25T00:00:00+01:00")
    assert response.status_code == 200
    data = response.get_json()
    assert data["error"] is None
    assert [(h["date"], h["name"]) for h in data["holidays"]] == [
        ("2026-12-24", "Heiligabend"), ("2026-12-25", "Erster Weihnachtstag"), ("2027-12-24", "Heiligabend"),
    ]
    assert sorted(upstream["calls"]) == ["2026", "2027"]


def test_cache_and_last_known_state_when_upstream_down(client, login, make_user, upstream, app):
    login(make_user())
    _get(client, "2026-12-01", "2027-01-01")
    _get(client, "2026-12-01", "2027-01-01")
    assert upstream["calls"] == ["2026"]  # zweiter Aufruf aus dem Zwischenspeicher

    app.config["HOLIDAY_CACHE_SECONDS"] = 0  # abgelaufen → neuer Abruf, der scheitert
    upstream["fail"] = True
    data = _get(client, "2026-12-01", "2027-01-01").get_json()
    assert [h["name"] for h in data["holidays"]] == ["Heiligabend", "Erster Weihnachtstag"]
    assert data["error"] is None

    data = _get(client, "2028-12-01", "2029-01-01").get_json()  # nie geladenes Jahr
    assert data["holidays"] == [] and data["error"]


def test_disabled_without_configuration(client, login, make_user, app):
    login(make_user())
    data = _get(client, "2026-12-01", "2027-01-01").get_json()
    assert data == {"holidays": [], "error": None}


def test_invalid_range(client, login, make_user, upstream):
    login(make_user())
    for start, end in (("x", "2026-01-01"), ("2026-02-01", "2026-01-01"), ("2026-01-01", "2029-01-01")):
        assert _get(client, start, end).status_code == 400
