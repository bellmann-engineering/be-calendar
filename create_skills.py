from app import create_app, db
from app.models import Skill

app = create_app()
with app.app_context():
    # Datos extraídos directamente de bellmann-engineering.com
    real_skills = [
        (
            "Agile Projekte mit Scrum",
            "Scrum dient dem agilen Management innovativer Produktentwicklung mit selbstorganisierten Teams.",
        ),
        (
            "Microservices mit Docker & Kubernetes",
            "Grundlegende Kenntnisse zum Thema Microservices, Docker Containern und Kubernetes.",
        ),
        ("Python Grundlagen", "Python Grundlagen lernen und anwenden."),
        (
            "C#.NET & Clean Code",
            "Coach für C#.NET, Python und SQL sowie Prinzipien für hochwertigen Code.",
        ),
        (
            "Datenschutz-Grundverordnung (EU-DSGVO)",
            "Anwendung der EU-Datenschutz-Grundverordnung in deutschen Unternehmen.",
        ),
        (
            "IT-Sicherheit",
            "Schutz von Unternehmensdaten und IT-Infrastruktur vor neuen Gefährdungspotenzialen.",
        ),
        (
            "Zeit- und Ressourcenmanagement",
            "Soft Skill: Umgang mit knappen Ressourcen und Druck.",
        ),
        (
            "Datenbankentwicklung mit SQL",
            "Basiswissen über Datenbanken, Datenbankmodellierung und SQL.",
        ),
    ]

    added = 0
    for name, desc in real_skills:
        if not Skill.query.filter_by(name=name).first():
            db.session.add(
                Skill(name=name, description=desc[:250])
            )  # Limitado a 255 chars por el modelo
            added += 1

    db.session.commit()
    print(
        f"✅ {added} echte Bellmann-Qualifikationen erfolgreich in die Datenbank geladen!"
    )
