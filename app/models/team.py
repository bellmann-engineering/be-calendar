"""
Tabelle ``teams`` – organisatorische Teams und ihre Leitung.

Beziehungen:
    * 1:n ``users`` über ``users.team_id``             -> ``Team.members``
    * n:1 ``users`` über ``teams.team_leader_id``      -> ``Team.leader``
      (Rückreferenz am User: ``user.led_team``)

Zirkuläre Fremdschlüssel (users -> teams -> users): ``use_alter=True`` sorgt dafür,
dass die Constraint erst nach dem Anlegen beider Tabellen erzeugt wird.

Wer benutzt das Model?
    TeamService (anlegen/zuordnen), EventService.list_visible_events (Teamleitung sieht
    Termine ihres Teams), AuthorizationService (Team-Prüfungen).
"""

from app import db


class Team(db.Model):
    """Fasst Mitarbeiter für eine teambezogene Terminverwaltung zusammen."""

    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    team_leader_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", name="fk_teams_team_leader_id", use_alter=True),
        nullable=True,
        # Index: "Welche Teams leitet User X?" (AdminService, UserService.delete_user)
        index=True,
    )

    leader = db.relationship(
        "User",
        foreign_keys=[team_leader_id],
        backref=db.backref("led_team", uselist=False),
    )
    members = db.relationship("User", foreign_keys="User.team_id", back_populates="team", lazy=True)

    def __repr__(self) -> str:
        """Liefert eine kompakte Debug-Repräsentation des Teams."""
        return f"<Team {self.name}>"
