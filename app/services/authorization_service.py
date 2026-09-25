"""
Zentrale Geschäftsregeln für rollen- und teambezogene Zugriffsprüfungen.

Was macht diese Datei?
    Sie beantwortet Fragen wie "Darf Person A das mit Person/Termin B tun?" – an EINER
    Stelle, damit nicht jede Route ihre eigenen (und irgendwann widersprüchlichen)
    Regeln hat. Jede Methode liefert ``(erlaubt: bool, fehlermeldung: str | None)``.

Die Rollen-Hierarchie (siehe ``app/models/role.py::ROLE_RANK``):
    CEO (4) > ADMIN (3) > TEAM_LEADER (2) > TRAINER (1)

Wer benutzt sie?
    EventService (Termine anlegen/ändern/löschen, Überbuchung),
    UserService (Benutzer anlegen/ändern/löschen/sperren, CSV-Import),
    AdminService (Rechte entziehen).

Wovon hängt sie ab?
    Nur von den Models – kein Datenbankzugriff, kein HTTP. Dadurch leicht testbar.
"""

from __future__ import annotations

from app.models import Event, RoleEnum, User
from app.models.role import ROLE_RANK


def _rank(role_name: str | None) -> int:
    """Rang einer Rolle; unbekannte Rollen bekommen 0 (= keinerlei Rechte)."""
    return ROLE_RANK.get(role_name or "", 0)


class AuthorizationService:
    """Kapselt Zugriffsentscheidungen unabhängig von Flask-Routen."""

    # ------------------------------------------------------------------ Benutzerverwaltung
    @staticmethod
    def can_manage_user(
        actor: User, target: User | None, new_role_name: str | None = None
    ) -> tuple[bool, str | None]:
        """Darf ``actor`` den Benutzer ``target`` anlegen/ändern/löschen/sperren?

        Regeln:
            * CEO darf alles.
            * ADMIN darf nur Benutzer UNTER sich verwalten (TEAM_LEADER, TRAINER) und
              nur diese Rollen vergeben. Sich selbst darf er bearbeiten (Name, Passwort),
              aber seine Rolle nicht ändern – sonst könnte er sich zum CEO befördern.
            * Alle anderen Rollen dürfen keine Benutzer verwalten.

        Args:
            actor: Der eingeloggte, ausführende Benutzer.
            target: Der betroffene Benutzer; None beim Anlegen eines neuen Benutzers.
            new_role_name: Die Rolle, die vergeben werden soll (oder None = unverändert).
        """
        actor_role = actor.role.name
        if actor_role == RoleEnum.CEO.value:
            return True, None
        if actor_role != RoleEnum.ADMIN.value:
            return False, "Ihre Rolle darf keine Benutzer verwalten."

        is_self = target is not None and target.id == actor.id
        if target is not None and not is_self and _rank(target.role.name) >= _rank(actor_role):
            return False, "Ein Admin darf keine anderen Admins oder den CEO verwalten."

        if new_role_name is not None:
            role_unchanged = is_self and new_role_name == actor_role
            if not role_unchanged and _rank(new_role_name) >= _rank(actor_role):
                return (
                    False,
                    "Ein Admin darf nur die Rollen TRAINER und TEAM_LEADER vergeben.",
                )
        return True, None

    # ------------------------------------------------------------------ Termine
    @staticmethod
    def can_manage_assignee(actor: User, assignee: User | None) -> tuple[bool, str | None]:
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
    def can_manage_event(actor: User, event: Event) -> tuple[bool, str | None]:
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
