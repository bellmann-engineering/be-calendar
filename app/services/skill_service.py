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
        name: str, actor_id: int, description: Optional[str] = None
    ) -> Tuple[Optional[Skill], Optional[str], int]:
        """Legt einen neuen, eindeutig benannten Skill an."""
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            return None, "Der Name der Qualifikation ist erforderlich.", 400
        if len(cleaned_name) > 100:
            return None, "Der Name darf höchstens 100 Zeichen enthalten.", 400

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
    def update_skill(
        skill_id: int, data: dict, actor_id: int
    ) -> Tuple[Optional[Skill], Optional[str], int]:
        """Aktualisiert eine bestehende Qualifikation."""
        skill = db.session.get(Skill, skill_id)
        if not skill:
            return None, "Qualifikation nicht gefunden.", 404

        name = data.get("name", skill.name).strip()
        if not name:
            return None, "Der Name der Qualifikation ist erforderlich.", 400

        existing = Skill.query.filter(db.func.lower(Skill.name) == name.lower()).first()
        if existing and existing.id != skill_id:
            return None, "Eine Qualifikation mit diesem Namen existiert bereits.", 409

        skill.name = name
        skill.description = data.get("description", skill.description)

        db.session.add(
            AuditLog(
                user_id=actor_id,
                action="UPDATE_SKILL",
                details_json={"skill_id": skill.id, "name": skill.name},
            )
        )

        try:
            db.session.commit()
            return skill, None, 200
        except Exception:
            db.session.rollback()
            return None, "Fehler beim Aktualisieren der Qualifikation.", 500

    @staticmethod
    def delete_skill(skill_id: int, actor_id: int) -> Tuple[bool, Optional[str], int]:
        """Löscht eine Qualifikation aus dem System."""
        skill = db.session.get(Skill, skill_id)
        if not skill:
            return False, "Qualifikation nicht gefunden.", 404

        db.session.add(
            AuditLog(
                user_id=actor_id,
                action="DELETE_SKILL",
                details_json={"skill_id": skill.id, "name": skill.name},
            )
        )
        db.session.delete(skill)

        try:
            db.session.commit()
            return True, None, 200
        except Exception:
            db.session.rollback()
            return False, "Fehler beim Löschen der Qualifikation.", 500

    @staticmethod
    def assign_skills(
        user_id: int, skill_ids: Iterable[Any], actor_id: int
    ) -> Tuple[Optional[User], Optional[str], int]:
        """Ersetzt die Skill-Zuordnung eines Mitarbeiters atomar."""
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
        """Findet aktive Mitarbeiter, die sämtliche angeforderten Skills besitzen."""
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
