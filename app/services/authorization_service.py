"""Zentrale Geschäftsregeln für rollen- und teambezogene Zugriffsprüfungen."""

from __future__ import annotations

from typing import Optional, Tuple

from app.models import Event, RoleEnum, User


class AuthorizationService:
    """Kapselt Zugriffsentscheidungen unabhängig von Flask-Routen."""

    @staticmethod
    def can_manage_assignee(
        actor: User, assignee: Optional[User]
    ) -> Tuple[bool, Optional[str]]:
        """Prüft, ob ein Benutzer einen Termin für die Zielperson anlegen darf.

        Args:
            actor: Eingeloggter Benutzer, der den Termin anlegen möchte.
            assignee: Zielperson des Termins; kann bei unternehmensweiten Terminen fehlen.

        Returns:
            Ein Tupel mit Erlaubnis und einer deutschen Fehlermeldung bei Ablehnung.
        """
        role_name = actor.role.name
        if role_name in {RoleEnum.CEO.value, RoleEnum.ADMIN.value}:
            return True, None

        if role_name != RoleEnum.TEAM_LEADER.value:
            return False, "Ihre Rolle darf keine Termine für andere Benutzer anlegen."
        if actor.team_id is None:
            return False, "Der Teamleitung ist kein Team zugeordnet."
        if assignee is None:
            return (
                False,
                "Teamtermine müssen einem Mitglied des eigenen Teams zugeordnet werden.",
            )
        if assignee.team_id != actor.team_id:
            return (
                False,
                "Termine dürfen nur Mitgliedern des eigenen Teams zugeordnet werden.",
            )
        return True, None

    @staticmethod
    def can_manage_event(actor: User, event: Event) -> Tuple[bool, Optional[str]]:
        """Prüft, ob ein Benutzer einen bestehenden Termin ändern oder löschen darf.

        Args:
            actor: Eingeloggter Benutzer, der die Änderung ausführen möchte.
            event: Zu schützender Kalendereintrag.

        Returns:
            Ein Tupel mit Erlaubnis und einer deutschen Fehlermeldung bei Ablehnung.
        """
        role_name = actor.role.name
        if role_name in {RoleEnum.CEO.value, RoleEnum.ADMIN.value}:
            return True, None
        if role_name != RoleEnum.TEAM_LEADER.value:
            return False, "Ihre Rolle darf diesen Termin nicht bearbeiten."
        if actor.team_id is None or event.assigned_to_id is None:
            return False, "Dieser Termin gehört nicht zum verwaltbaren Teamkontext."
        if event.assigned_to is None or event.assigned_to.team_id != actor.team_id:
            return False, "Dieser Termin gehört nicht zum eigenen Team."
        return True, None

    @staticmethod
    def can_override_conflict(
        actor: User, requested_override: bool
    ) -> Tuple[bool, Optional[str]]:
        """Prüft die explizite CEO-Freigabe für eine kollidierende Überbuchung.

        Args:
            actor: Eingeloggter Benutzer, der die Überbuchung auslösen möchte.
            requested_override: Vom Client gesetzte, bewusste Bestätigung.

        Returns:
            Ein Tupel mit Erlaubnis und einer deutschen Fehlermeldung bei Ablehnung.
        """
        if actor.role.name != RoleEnum.CEO.value:
            return (
                False,
                "Eine Terminüberbuchung darf ausschließlich durch den CEO freigegeben werden.",
            )
        if not requested_override:
            return (
                False,
                "Die CEO-Überbuchung muss mit override_conflict=true ausdrücklich bestätigt werden.",
            )
        return True, None
