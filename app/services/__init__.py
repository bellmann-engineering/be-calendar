"""
Service-Schicht (Geschäftslogik).

Aufbau der Anwendung in Schichten ("Clean Architecture light"):

    Browser ──HTTP──> Nginx ──> Routen (app/routes)      : HTTP rein/raus, JSON, Auth-Dekoratoren
                                   │
                                   ▼
                               Services (dieses Paket)   : Regeln, Validierung, Transaktionen
                                   │
                                   ▼
                               Models (app/models)       : Tabellen über SQLAlchemy
                                   │
                                   ▼
                               PostgreSQL

Regeln für Services:
    * Kein Zugriff auf ``request``/``jsonify`` – Services kennen kein HTTP. Sie liefern
      Tupel wie ``(ergebnis, fehlertext, statuscode)`` zurück; die Route baut daraus JSON.
    * Sie committen selbst (eine Transaktion pro Anwendungsfall) und machen bei Fehlern
      ``db.session.rollback()``.
    * Nebenwirkungen nach außen (E-Mail, Google) erst NACH dem Commit
      (``app/utils/transaction.py``).
"""
