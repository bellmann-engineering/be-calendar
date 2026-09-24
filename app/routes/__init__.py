"""
HTTP-Schicht: Flask-Blueprints (Routen-Gruppen).

Jede Datei definiert einen Blueprint mit URL-Präfix; registriert werden sie in
``app/__init__.py::create_app()``. Routen enthalten keine Geschäftslogik – sie lesen den
Request, rufen einen Service auf und wandeln das Ergebnis in JSON um.
"""
