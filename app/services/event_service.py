from datetime import datetime, timedelta, timezone
from app import db
from app.models import AuditLog, Event, EventRSVP, RoleEnum, RSVPStatusEnum, User
from app.services.authorization_service import AuthorizationService
from app.services.notification_service import NotificationService


class EventService:
    @staticmethod
    def _normalize_dt(dt: datetime) -> datetime:
        if dt is None:
            return None
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    @staticmethod
    def validate_buffers(buffer_before: int, buffer_after: int, role_name: str):
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (buffer_before, buffer_after)
        ):
            return "Pufferzeiten müssen ganze Zahlen sein."
        if buffer_before < 0 or buffer_after < 0:
            return "Pufferzeiten dürfen keine negativen Werte enthalten."
        if role_name != RoleEnum.CEO.value and not (
            15 <= buffer_before <= 30 and 15 <= buffer_after <= 30
        ):
            return (
                "Für Nicht-CEOs müssen Pufferzeiten zwischen 15 und 30 Minuten liegen."
            )
        return None

    @staticmethod
    def check_conflict(
        assigned_to_id,
        start_time,
        end_time,
        buffer_before=0,
        buffer_after=0,
        exclude_event_id=None,
    ):
        if not assigned_to_id:
            return None

        st_norm = EventService._normalize_dt(start_time)
        et_norm = EventService._normalize_dt(end_time)
        new_effective_start = st_norm - timedelta(minutes=buffer_before)
        new_effective_end = et_norm + timedelta(minutes=buffer_after)

        query = Event.query.filter(
            Event.assigned_to_id == assigned_to_id, not Event.is_deleted
        )
        if exclude_event_id:
            query = query.filter(Event.id != exclude_event_id)

        for event in query.all():
            e_st = EventService._normalize_dt(event.start_time)
            e_et = EventService._normalize_dt(event.end_time)
            existing_effective_start = e_st - timedelta(
                minutes=event.buffer_before_mins
            )
            existing_effective_end = e_et + timedelta(minutes=event.buffer_after_mins)

            if (
                existing_effective_start < new_effective_end
                and existing_effective_end > new_effective_start
            ):
                return event

        user = db.session.get(User, assigned_to_id)
        if user and getattr(user, "google_calendar_id", None):
            try:
                from app.services.calendar_service import GoogleCalendarService

                google_service = GoogleCalendarService()
                busy_times = google_service.get_busy_times(
                    user.google_calendar_id, new_effective_start, new_effective_end
                )

                if busy_times:
                    b_start = datetime.fromisoformat(
                        busy_times[0]["start"].replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                    b_end = datetime.fromisoformat(
                        busy_times[0]["end"].replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                    conflict_event = Event(
                        id=0,
                        title="Privater Termin (Google Kalender)",
                        start_time=b_start,
                        end_time=b_end,
                    )
                    return conflict_event
            except Exception:
                pass

        return None

    @staticmethod
    def create_event(data: dict, creator_id: int):
        try:
            start_time = datetime.fromisoformat(
                data["start_time"].replace("Z", "+00:00")
            )
            end_time = datetime.fromisoformat(data["end_time"].replace("Z", "+00:00"))
            start_time = EventService._normalize_dt(start_time)
            end_time = EventService._normalize_dt(end_time)
        except (ValueError, KeyError, TypeError):
            return None, "Ungültiges Datumsformat (ISO-8601 erforderlich).", 400

        if end_time <= start_time:
            return None, "Die Endzeit des Termins muss nach der Startzeit liegen.", 400

        creator = db.session.get(User, creator_id)
        if creator is None or not creator.is_active:
            return (
                None,
                "Der ausführende Benutzer wurde nicht gefunden oder ist nicht aktiv.",
                401,
            )

        buffer_before = data.get("buffer_before_mins", 15)
        buffer_after = data.get("buffer_after_mins", 15)
        buffer_error = EventService.validate_buffers(
            buffer_before, buffer_after, creator.role.name
        )
        if buffer_error:
            return None, buffer_error, 400

        assigned_to_id = data.get("assigned_to_id")
        assigned_user = None
        if assigned_to_id:
            assigned_user = db.session.get(User, assigned_to_id)
            if not assigned_user:
                return None, f"Benutzer mit ID {assigned_to_id} nicht gefunden.", 404

        allowed, authorization_error = AuthorizationService.can_manage_assignee(
            creator, assigned_user
        )
        if not allowed:
            return None, authorization_error, 403

        conflict = EventService.check_conflict(
            assigned_to_id, start_time, end_time, buffer_before, buffer_after
        )
        is_override = False
        if conflict:
            is_override, override_error = AuthorizationService.can_override_conflict(
                creator, data.get("override_conflict") is True
            )
            if not is_override:
                return (
                    None,
                    f"Kollision mit bestehendem Termin: '{conflict.title}'. {override_error}",
                    409,
                )

        try:
            new_event = Event(
                title=data["title"],
                description=data.get("description", ""),
                start_time=start_time,
                end_time=end_time,
                buffer_before_mins=buffer_before,
                buffer_after_mins=buffer_after,
                created_by_id=creator_id,
                assigned_to_id=assigned_to_id,
                is_all_day=data.get("is_all_day", False),
                customer_id=data.get("customer_id"),
                meeting_link=data.get("meeting_link"),
            )
            db.session.add(new_event)
            db.session.flush()

            if assigned_to_id:
                rsvp = EventRSVP(
                    event_id=new_event.id,
                    user_id=assigned_to_id,
                    status=RSVPStatusEnum.PENDING.value,
                )
                db.session.add(rsvp)
                NotificationService.notify_user(
                    user_id=assigned_to_id,
                    title="Neuer Termin zugewiesen",
                    message=f"Ihnen wurde der Termin '{new_event.title}' zugewiesen.",
                    notification_type="EVENT_ASSIGNED",
                )

            audit = AuditLog(
                event_id=new_event.id,
                user_id=creator_id,
                action="CREATE_EVENT",
                details_json={
                    "title": new_event.title,
                    "start_time": new_event.start_time.isoformat(),
                    "end_time": new_event.end_time.isoformat(),
                    "assigned_to_id": assigned_to_id,
                },
            )
            db.session.add(audit)
            if is_override:
                db.session.add(
                    AuditLog(
                        event_id=new_event.id,
                        user_id=creator_id,
                        action="CEO_OVERRIDE_CONFLICT",
                        details_json={
                            "conflicting_event_id": conflict.id,
                            "conflicting_event_title": conflict.title,
                            "override_confirmed": True,
                        },
                    )
                )
            db.session.commit()

            if assigned_user and getattr(assigned_user, "google_calendar_id", None):
                try:
                    from app.services.calendar_service import GoogleCalendarService

                    g_service = GoogleCalendarService()
                    g_id = g_service.insert_event(
                        calendar_id=assigned_user.google_calendar_id,
                        title=new_event.title,
                        start_time=new_event.start_time,
                        end_time=new_event.end_time,
                        description=new_event.description,
                    )
                    if g_id:
                        new_event.google_event_id = g_id
                        db.session.commit()
                except Exception:
                    pass

            return new_event, None, 201

        except Exception as e:
            db.session.rollback()
            return None, f"Datenbankfehler: {str(e)}", 500

    @staticmethod
    def soft_delete_event(event_id: int, user_id: int):
        event = Event.query.get(event_id)
        if not event or event.is_deleted:
            return False, "Termin nicht gefunden.", 404

        actor = db.session.get(User, user_id)
        if actor is None or not actor.is_active:
            return False, "Ausführender Benutzer inaktiv.", 401

        allowed, authorization_error = AuthorizationService.can_manage_event(
            actor, event
        )
        if not allowed:
            return False, authorization_error, 403

        try:
            event.is_deleted = True
            event.deleted_at = datetime.now(timezone.utc)

            if getattr(event, "google_event_id", None) and getattr(
                event, "assigned_to_id", None
            ):
                try:
                    from app.services.calendar_service import GoogleCalendarService

                    del_user = db.session.get(User, event.assigned_to_id)
                    if del_user and getattr(del_user, "google_calendar_id", None):
                        GoogleCalendarService().delete_event(
                            del_user.google_calendar_id, event.google_event_id
                        )
                except Exception:
                    pass

            audit = AuditLog(
                event_id=event.id,
                user_id=user_id,
                action="DELETE_EVENT",
                details_json={"deleted_at": event.deleted_at.isoformat()},
            )
            db.session.add(audit)
            db.session.commit()
            return True, None, 200
        except Exception as e:
            db.session.rollback()
            return False, f"Datenbankfehler: {str(e)}", 500

    @staticmethod
    def update_event(event_id: int, data: dict, user_id: int):
        event = Event.query.filter_by(id=event_id, is_deleted=False).first()
        if event is None:
            return None, "Termin nicht gefunden.", 404

        actor = db.session.get(User, user_id)
        if actor is None or not actor.is_active:
            return None, "Ausführender Benutzer inaktiv.", 401

        allowed, authorization_error = AuthorizationService.can_manage_event(
            actor, event
        )
        if not allowed:
            return None, authorization_error, 403

        try:
            start_time = (
                EventService._normalize_dt(
                    datetime.fromisoformat(data["start_time"].replace("Z", "+00:00"))
                )
                if "start_time" in data
                else EventService._normalize_dt(event.start_time)
            )
            end_time = (
                EventService._normalize_dt(
                    datetime.fromisoformat(data["end_time"].replace("Z", "+00:00"))
                )
                if "end_time" in data
                else EventService._normalize_dt(event.end_time)
            )
        except (TypeError, ValueError):
            return None, "Ungültiges Datumsformat.", 400

        if end_time <= start_time:
            return None, "Endzeit muss nach Startzeit liegen.", 400

        buffer_before = data.get("buffer_before_mins", event.buffer_before_mins or 15)
        buffer_after = data.get("buffer_after_mins", event.buffer_after_mins or 15)
        buffer_error = EventService.validate_buffers(
            buffer_before, buffer_after, actor.role.name
        )
        if buffer_error:
            return None, buffer_error, 400

        assigned_to_id = data.get("assigned_to_id", event.assigned_to_id)
        assigned_user = None
        if assigned_to_id is not None:
            if isinstance(assigned_to_id, bool) or not isinstance(assigned_to_id, int):
                return None, "assigned_to_id muss null oder int sein.", 400
            assigned_user = db.session.get(User, assigned_to_id)
            if assigned_user is None:
                return None, "Zugewiesener Benutzer nicht gefunden.", 404
            allowed, authorization_error = AuthorizationService.can_manage_assignee(
                actor, assigned_user
            )
            if not allowed:
                return None, authorization_error, 403
        elif actor.role.name == "TEAM_LEADER":
            return (
                None,
                "Teamleitungen dürfen keinen Termin ohne Teammitglied freigeben.",
                403,
            )

        conflict = EventService.check_conflict(
            assigned_to_id,
            start_time,
            end_time,
            buffer_before,
            buffer_after,
            exclude_event_id=event.id,
        )
        is_override = False
        if conflict:
            is_override, override_error = AuthorizationService.can_override_conflict(
                actor, data.get("override_conflict") is True
            )
            if not is_override:
                return (
                    None,
                    f"Kollision mit bestehendem Termin: '{conflict.title}'. {override_error}",
                    409,
                )

        if "title" in data and (
            not isinstance(data["title"], str) or not data["title"].strip()
        ):
            return None, "Titel darf nicht leer sein.", 400

        previous_values = {
            "title": event.title,
            "start_time": event.start_time.isoformat(),
            "end_time": event.end_time.isoformat(),
            "assigned_to_id": event.assigned_to_id,
            "buffer_before_mins": event.buffer_before_mins,
            "buffer_after_mins": event.buffer_after_mins,
            "reallocation_required": event.reallocation_required,
        }
        assignment_changed = assigned_to_id != event.assigned_to_id

        try:
            event.title = (
                data.get("title", event.title).strip()
                if "title" in data
                else event.title
            )
            event.description = data.get("description", event.description)
            event.start_time = start_time
            event.end_time = end_time
            event.buffer_before_mins = buffer_before
            event.buffer_after_mins = buffer_after
            event.assigned_to_id = assigned_to_id
            event.is_all_day = data.get(
                "is_all_day", getattr(event, "is_all_day", False)
            )
            event.customer_id = data.get(
                "customer_id", getattr(event, "customer_id", None)
            )
            event.meeting_link = data.get("meeting_link", event.meeting_link)
            event.reallocation_required = assigned_to_id is None

            if assignment_changed and assigned_to_id is not None:
                rsvp = EventRSVP.query.filter_by(
                    event_id=event.id, user_id=assigned_to_id
                ).first()
                if rsvp is None:
                    db.session.add(
                        EventRSVP(
                            event_id=event.id,
                            user_id=assigned_to_id,
                            status=RSVPStatusEnum.PENDING.value,
                        )
                    )
                else:
                    rsvp.status = RSVPStatusEnum.PENDING.value
                    rsvp.rejection_reason = None
                NotificationService.notify_user(
                    user_id=assigned_to_id,
                    title="Neuer Termin",
                    message=f"Termin '{event.title}' zugewiesen.",
                    notification_type="EVENT_ASSIGNED",
                )

            db.session.add(
                AuditLog(
                    event_id=event.id,
                    user_id=user_id,
                    action="CEO_OVERRIDE_UPDATE" if is_override else "UPDATE_EVENT",
                    details_json={
                        "previous": previous_values,
                        "new": {
                            "title": event.title,
                            "start_time": event.start_time.isoformat(),
                            "end_time": event.end_time.isoformat(),
                            "assigned_to_id": event.assigned_to_id,
                            "buffer_before_mins": event.buffer_before_mins,
                            "buffer_after_mins": event.buffer_after_mins,
                            "reallocation_required": event.reallocation_required,
                        },
                        "conflict_overridden": is_override,
                        "conflicting_event_id": conflict.id if conflict else None,
                    },
                )
            )
            db.session.commit()
            return event, None, 200
        except Exception:
            db.session.rollback()
            return None, "Termin konnte nicht aktualisiert werden.", 500

    @staticmethod
    def list_visible_events(user_id: int):
        actor = db.session.get(User, user_id)
        if actor is None or not actor.is_active:
            return None, "Benutzer nicht gefunden.", 401
        base_query = Event.query.filter_by(is_deleted=False)
        role_name = actor.role.name
        if role_name in {"CEO", "ADMIN"}:
            return base_query.all(), None, 200
        if role_name == "TRAINER":
            return base_query.filter_by(assigned_to_id=actor.id).all(), None, 200
        if role_name == "TEAM_LEADER":
            if actor.team_id is None:
                return [], None, 200
            return (
                base_query.join(User, Event.assigned_to_id == User.id)
                .filter(User.team_id == actor.team_id)
                .all(),
                None,
                200,
            )
        return [], None, 200
