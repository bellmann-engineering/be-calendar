"""Geschäftslogik für dynamische Qualifikations-Tags."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

from sqlalchemy import select

from app import db
from app.models import AuditLog, RoleEnum, Skill, User


class SkillService:
    """Kapselt CRUD- und Zuordnungslogik für Mitarbeiterqualifikationen."""

    @staticmethod
    def create_skill(
        name: str,
        actor_id: int,
        description: Optional[str] = None,
    ) -> Tuple[Optional[Skill], Optional[str], int]:
        """Legt einen neuen, eindeutig benannten Skill an.

        Args:
            name: Sichtbarer Name der Qualifikation.
            actor_id: Primärschlüssel des berechtigten, ausführenden Benutzers.
            description: Optionale Erläuterung der Qualifikation.

        Returns:
            Ein Tupel aus Skill, Fehlermeldung und HTTP-Statuscode.
        """
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            return None, "Der Name der Qualifikation ist erforderlich.", 400
        if len(cleaned_name) > 100:
            return (
                None,
                "Der Name der Qualifikation darf höchstens 100 Zeichen enthalten.",
                400,
            )
        cleaned_description = (description or "").strip() or None
        if cleaned_description and len(cleaned_description) > 255:
            return None, "Die Beschreibung darf höchstens 255 Zeichen enthalten.", 400
        if Skill.query.filter(
            db.func.lower(Skill.name) == cleaned_name.lower()
        ).first():
            return None, "Eine Qualifikation mit diesem Namen existiert bereits.", 409

        skill = Skill(name=cleaned_name, description=cleaned_description)
        db.session.add(skill)
        db.session.flush()
        db.session.add(
            AuditLog(
                user_id=actor_id,
                action="CREATE_SKILL",
                details_json={"skill_id": skill.id, "name": skill.name},
            )
        )
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return None, "Die Qualifikation konnte nicht gespeichert werden.", 500
        return skill, None, 201

    @staticmethod
    def assign_skills(
        user_id: int,
        skill_ids: Iterable[Any],
        actor_id: int,
    ) -> Tuple[Optional[User], Optional[str], int]:
        """Ersetzt die Skill-Zuordnung eines Mitarbeiters atomar.

        Args:
            user_id: Primärschlüssel des Mitarbeiters.
            skill_ids: Vollständige Liste der künftig zugeordneten Skill-IDs.
            actor_id: Primärschlüssel des berechtigten, ausführenden Benutzers.

        Returns:
            Ein Tupel aus Benutzer, Fehlermeldung und HTTP-Statuscode.
        """
        if not isinstance(skill_ids, list) or not all(
            isinstance(skill_id, int) for skill_id in skill_ids
        ):
            return None, "skill_ids muss eine Liste ganzer Zahlen sein.", 400
        if len(skill_ids) != len(set(skill_ids)):
            return None, "skill_ids darf keine doppelten Einträge enthalten.", 400

        user = db.session.get(User, user_id)
        if user is None:
            return None, "Benutzer nicht gefunden.", 404

        skills = (
            list(db.session.scalars(select(Skill).where(Skill.id.in_(skill_ids))).all())
            if skill_ids
            else []
        )
        found_ids = {skill.id for skill in skills}
        missing_ids = sorted(set(skill_ids) - found_ids)
        if missing_ids:
            return (
                None,
                f"Die folgenden Qualifikationen existieren nicht: {missing_ids}.",
                404,
            )

        previous_skill_ids = sorted(skill.id for skill in user.skills)
        user.skills = skills
        db.session.add(
            AuditLog(
                user_id=actor_id,
                action="ASSIGN_SKILLS",
                details_json={
                    "target_user_id": user.id,
                    "previous_skill_ids": previous_skill_ids,
                    "new_skill_ids": sorted(skill_ids),
                },
            )
        )
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return None, "Die Skill-Zuordnungen konnten nicht gespeichert werden.", 500
        return user, None, 200

    @staticmethod
    def list_skills() -> List[Skill]:
        """Liefert alle dynamisch konfigurierten Qualifikationen alphabetisch."""
        return Skill.query.order_by(Skill.name.asc()).all()

    @staticmethod
    def list_users_by_skills(
        skill_ids: Iterable[Any],
    ) -> Tuple[Optional[List[User]], Optional[str], int]:
        """Findet aktive Mitarbeiter, die sämtliche angeforderten Skills besitzen.

        Args:
            skill_ids: Skill-IDs, die ein Mitarbeiter vollständig erfüllen muss.

        Returns:
            Ein Tupel aus Benutzern, Fehlermeldung und HTTP-Statuscode.
        """
        if (
            not isinstance(skill_ids, list)
            or not skill_ids
            or not all(isinstance(skill_id, int) for skill_id in skill_ids)
        ):
            return (
                None,
                "skill_ids muss eine nicht leere Liste ganzer Zahlen sein.",
                400,
            )
        if len(skill_ids) != len(set(skill_ids)):
            return None, "skill_ids darf keine doppelten Einträge enthalten.", 400

        skills = list(
            db.session.scalars(select(Skill).where(Skill.id.in_(skill_ids))).all()
        )
        if len(skills) != len(skill_ids):
            return (
                None,
                "Mindestens eine angeforderte Qualifikation existiert nicht.",
                404,
            )

        users = User.query.filter_by(is_active=True).all()
        requested_ids = set(skill_ids)
        matching_users = [
            user
            for user in users
            if user.role.name == RoleEnum.TRAINER.value
            and requested_ids.issubset({skill.id for skill in user.skills})
        ]
        return matching_users, None, 200
