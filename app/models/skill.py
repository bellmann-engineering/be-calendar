from app import db

# Hilfstabelle für die Viele-zu-Viele-Beziehung zwischen Benutzern und Skills
user_skills = db.Table(
    "user_skills",
    db.Column(
        "user_id",
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "skill_id",
        db.Integer,
        db.ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

event_required_skills = db.Table(
    "event_required_skills",
    db.Column(
        "event_id",
        db.Integer,
        db.ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "skill_id",
        db.Integer,
        db.ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Skill(db.Model):
    """Dynamische Qualifikations-Tags für Trainer."""

    __tablename__ = "skills"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f"<Skill {self.name}>"
