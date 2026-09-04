"""Geschäftslogik für Teams und deren Mitgliederzuordnungen."""

from __future__ import annotations

from typing import Optional, Tuple

from app import db
from app.models import AuditLog, RoleEnum, Team, User


class TeamService:
    """Kapselt transaktionssichere Teamverwaltung mit Audit-Protokollierung."""

    @staticmethod
    def create_team(
        name: str, team_leader_id: Optional[int], actor_id: int
    ) -> Tuple[Optional[Team], Optional[str], int]:
        """Erstellt ein Team und ordnet optional eine gültige Teamleitung zu.

        Args:
            name: Eindeutige, sichtbare Teambezeichnung.
            team_leader_id: Optionale ID eines Benutzers mit Rolle TEAM_LEADER.
            actor_id: ID des berechtigten, ausführenden Benutzers.

        Returns:
            Team, Fehlertext und passender HTTP-Statuscode.
        """
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            return None, "Der Teamname ist erforderlich.", 400
        if len(cleaned_name) > 100:
            return None, "Der Teamname darf höchstens 100 Zeichen enthalten.", 400
        if Team.query.filter(db.func.lower(Team.name) == cleaned_name.lower()).first():
            return None, "Ein Team mit diesem Namen existiert bereits.", 409

        leader = None
        if team_leader_id is not None:
            leader = db.session.get(User, team_leader_id)
            if leader is None:
                return None, "Die angegebene Teamleitung wurde nicht gefunden.", 404
            if leader.role.name != RoleEnum.TEAM_LEADER.value:
                return (
                    None,
                    "Die angegebene Person besitzt nicht die Rolle TEAM_LEADER.",
                    400,
                )

        try:
            team = Team(name=cleaned_name, leader=leader)
            db.session.add(team)
            db.session.flush()
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
        except Exception:
            db.session.rollback()
            return None, "Das Team konnte nicht gespeichert werden.", 500

    @staticmethod
    def assign_member(
        team_id: int, user_id: int, actor_id: int
    ) -> Tuple[Optional[User], Optional[str], int]:
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
            return (
                None,
                "Eine Teamleitung kann nicht in ein fremdes Team verschoben werden.",
                409,
            )

        previous_team_id = user.team_id
        try:
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
        except Exception:
            db.session.rollback()
            return None, "Die Teamzuordnung konnte nicht gespeichert werden.", 500
