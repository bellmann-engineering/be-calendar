"""
Tests für Kunden: Kürzel, Logo-Upload und das Erkennen von Kunden im Termintitel.

Geprüft wird vor allem:
    * Logos werden serverseitig neu als kleines PNG kodiert; SVG und Nicht-Bilder
      werden abgelehnt (SVG kann JavaScript enthalten).
    * Nur CEO/ADMIN dürfen Logos ändern, jeder Angemeldete darf sie sehen.
    * "(GFN)" bzw. "(Comcave/CC)" im Titel ordnet den Termin dem Kunden zu (tag).
"""

import io

from PIL import Image


def _png(width=600, height=300, color=(200, 30, 30, 255)) -> io.BytesIO:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _kunde(client, csrf, name, codes=None):
    response = client.post(
        "/api/v1/customers",
        json={"name": name, "color_hex": "#0F766E", "short_codes": codes},
        headers=csrf(),
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["id"]


def test_kuerzel_werden_gespeichert_und_geprueft(client, make_user, login, csrf):
    login(make_user("CEO"))
    kunde_id = _kunde(client, csrf, "Comcave", "CC, cc,  Comcave College ")
    kunde = next(c for c in client.get("/api/v1/customers").get_json() if c["id"] == kunde_id)
    # Doppelte (ohne Groß-/Kleinschreibung) und Leerzeichen fallen weg.
    assert kunde["short_codes"] == ["CC", "Comcave College"]
    assert kunde["logo_url"] is None
    ungueltig = client.put(
        f"/api/v1/customers/{kunde_id}", json={"short_codes": "A/B"}, headers=csrf()
    )
    assert ungueltig.status_code == 400


def test_logo_hochladen_verkleinern_ausliefern_entfernen(client, make_user, login, csrf):
    login(make_user("ADMIN"))
    kunde_id = _kunde(client, csrf, "GFN", "GFN")
    upload = client.put(
        f"/api/v1/customers/{kunde_id}/logo",
        data={"file": (_png(), "logo.png")},
        headers=csrf(),
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200, upload.get_json()
    url = upload.get_json()["logo_url"]
    assert f"/api/v1/customers/{kunde_id}/logo?v=" in url

    bild = client.get(url)
    assert bild.status_code == 200
    assert bild.mimetype == "image/png"
    assert "immutable" in bild.headers["Cache-Control"]
    with Image.open(io.BytesIO(bild.data)) as png:
        assert max(png.size) <= 256  # serverseitig verkleinert

    assert client.delete(f"/api/v1/customers/{kunde_id}/logo", headers=csrf()).status_code == 200
    assert client.get(f"/api/v1/customers/{kunde_id}/logo").status_code == 404


def test_svg_und_nicht_bilder_werden_abgelehnt(client, make_user, login, csrf):
    login(make_user("CEO"))
    kunde_id = _kunde(client, csrf, "Kunde")
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    for inhalt, name in [(svg, "logo.svg"), (b"kein Bild", "logo.png")]:
        antwort = client.put(
            f"/api/v1/customers/{kunde_id}/logo",
            data={"file": (io.BytesIO(inhalt), name)},
            headers=csrf(),
            content_type="multipart/form-data",
        )
        assert antwort.status_code == 400, name


def test_nur_ceo_und_admin_aendern_logos_alle_sehen_sie(client, make_user, login, csrf):
    ceo = make_user("CEO")
    trainer = make_user("TRAINER")
    login(ceo)
    kunde_id = _kunde(client, csrf, "GFN")
    client.put(
        f"/api/v1/customers/{kunde_id}/logo",
        data={"file": (_png(), "logo.png")},
        headers=csrf(),
        content_type="multipart/form-data",
    )
    client.post("/api/v1/auth/logout")

    login(trainer)
    assert client.get(f"/api/v1/customers/{kunde_id}/logo").status_code == 200
    verboten = client.put(
        f"/api/v1/customers/{kunde_id}/logo",
        data={"file": (_png(), "logo.png")},
        headers=csrf(),
        content_type="multipart/form-data",
    )
    assert verboten.status_code == 403


def test_kunde_wird_im_termintitel_erkannt(client, make_user, login, csrf):
    login(make_user("CEO"))
    gfn = _kunde(client, csrf, "GFN AG", "GFN")
    comcave = _kunde(client, csrf, "Comcave", "CC")
    titel = {
        "Schulung LF-VT3b (GFN)": ("GFN", gfn),
        "Prüfung (Comcave/CC)": ("CC", comcave),
        "Termin (gfn)": ("GFN", gfn),
        "Ohne Kunde": None,
        "Klammer ohne Treffer (XYZ)": None,
    }
    for t in titel:
        client.post(
            "/api/v1/events",
            json={
                "title": t,
                "start_time": "2026-10-01T10:00:00+02:00",
                "end_time": "2026-10-01T11:00:00+02:00",
            },
            headers=csrf(),
        )
    termine = {e["title"]: e["tag"] for e in client.get("/api/v1/events").get_json()}
    for t, erwartet in titel.items():
        if erwartet is None:
            assert termine[t] is None, t
        else:
            assert (termine[t]["label"], termine[t]["customer_id"]) == erwartet, t

    # Ein in der App gewählter Kunde hat Vorrang vor dem Titel.
    client.post(
        "/api/v1/events",
        json={
            "title": "Workshop (GFN)",
            "start_time": "2026-10-02T10:00:00+02:00",
            "end_time": "2026-10-02T11:00:00+02:00",
            "customer_id": comcave,
        },
        headers=csrf(),
    )
    workshop = next(
        e for e in client.get("/api/v1/events").get_json() if e["title"] == "Workshop (GFN)"
    )
    assert workshop["tag"]["customer_id"] == comcave
