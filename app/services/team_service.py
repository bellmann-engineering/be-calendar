"""
Geschäftslogik für Teams und deren Mitgliederzuordnungen.

Wer benutzt sie?
    ``app/routes/team_routes.py`` -> POST /api/v1/teams, PUT /api/v1/teams/<id>/members/<uid>
    (nur CEO/ADMIN).

Womit spricht sie?
    Tabellen ``teams``, ``users``, ``audit_logs``.

Warum sind Teams wichtig?
    Eine Teamleitung darf nur Termine für Mitglieder IHRES Teams anlegen/ändern und sieht
    nur deren Termine (siehe AuthorizationService und EventService.list_visible_events).
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app import db
from app.models import AuditLog, RoleEnum, Team, User

TeamResult = tuple[Team | None, str | None, int]
MemberResult = tuple[User | None, str | None, int]


class TeamService:
    """Kapselt transaktionssichere Teamverwaltung mit Audit-Protokollierung."""

    @staticmethod
    def create_team(name: str | None, team_leader_id: int | None, actor_id: int) -> TeamResult:
        """Erstellt ein Team und ordnet optional eine gültige Teamleitung zu.

        Args:
            name: Eindeutige, sichtbare Teambezeichnung.
            team_leader_id: Optionale ID eines Benutzers mit Rolle TEAM_LEADER.
            actor_id: ID des berechtigten, ausführenden Benutzers.

        Returns:
            Team, Fehlertext und passender HTTP-Statuscode.
        """
        cleaned_name = (name or "").strip() if isinstance(name, str) else ""
        if not cleaned_name:
            return None, "Der Teamname ist erforderlich.", 400
        if len(cleaned_name) > 100:
            return None, "Der Teamname darf höchstens 100 Zeichen enthalten.", 400
        # Vergleich ohne Groß-/Kleinschreibung: "Vertrieb" und "vertrieb" sind dasselbe Team.
        if Team.query.filter(db.func.lower(Team.name) == cleaned_name.lower()).first():
            return None, "Ein Team mit diesem Namen existiert bereits.", 409

        leader = None
        if team_leader_id is not None:
            leader = db.session.get(User, team_leader_id)
            if leader is None:
                return None, "Die angegebene Teamleitung wurde nicht gefunden.", 404
            if leader.role.name != RoleEnum.TEAM_LEADER.value:
                return None, "Die angegebene Person besitzt nicht die Rolle TEAM_LEADER.", 400

        team = Team(name=cleaned_name, leader=leader)
        db.session.add(team)
        try:
            db.session.flush()
        except IntegrityError:
            # Zwei gleichzeitige Anfragen mit demselben Namen: die UNIQUE-Constraint gewinnt.
            db.session.rollback()
            return None, "Ein Team mit diesem Namen existiert bereits.", 409
        if leader is not None:
            leader.team_id = team.id
        db.session.add(
            AuditLog(
                user_id=actor_id,
                action="CREATE_TEAM",
                details_json={"team_id": team.id, "name": team.name},
            )
        )
        db.session.commit()
        return team, None, 201

    @staticmethod
    def assign_member(team_id: int, user_id: int, actor_id: int) -> MemberResult:
        """Ordnet einen Benutzer einem Team zu und protokolliert die Änderung.

        Args:
            team_id: Primärschlüssel des Zielteams.
            user_id: Primärschlüssel des zuzuordnenden Benutzers.
            actor_id: ID des berechtigten, ausführenden Benutzers.

        Returns:
            Benutzer, Fehlertext und passender HTTP-Statuscode.
        """
        team = db.session.get(Team, team_id)
        if team is None:
            return None, "Team nicht gefunden.", 404
        user = db.session.get(User, user_id)
        if user is None:
            return None, "Benutzer nicht gefunden.", 404
        if user.led_team is not None and user.led_team.id != team.id:
            return None, "Eine Teamleitung kann nicht in ein fremdes Team verschoben werden.", 409

        previous_team_id = user.team_id
        user.team_id = team.id
        db.session.add(
            AuditLog(
                user_id=actor_id,
                action="ASSIGN_TEAM_MEMBER",
                details_json={
                    "target_user_id": user.id,
                    "previous_team_id": previous_team_id,
                    "new_team_id": team.id,
                },
            )
        )
        db.session.commit()
        return user, None, 200
