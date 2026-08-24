"""Concrete CalDAVAdapter backed by python-caldav.

MODULE CONTRACT
- Calls only the injected BaseURLProvider plus the third-party CalDAV library.
- Provides the full CalDAVAdapter contract for Task/Event CRUD and collections.
- Must not read Settings/SQLite, perform LAN discovery, prompt the user, or
  contain Task/Event business rules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Callable, Protocol

from ...api import Event, Task
from ...api.v1.errors import (
    AmbiguousError,
    ConflictError,
    NotFoundError,
    PermissionError as AssistantPermissionError,
    UnavailableError,
    ValidationError,
)


class BaseURLProvider(Protocol):
    """Minimal dependency supplied by bootstrap."""

    def get_base_url(self) -> str:
        ...


def _credentials(value: Any) -> dict[str, str]:
    """Translate internal credential data into DAVClient arguments."""

    if value is None:
        return {}

    username = None
    password = None

    if isinstance(value, Mapping):
        username = (
            value.get("username")
            or value.get("user")
            or value.get("login")
        )
        password = value.get("password")

    elif isinstance(value, (tuple, list)) and len(value) == 2:
        username, password = value

    else:
        username = getattr(value, "username", None)
        password = getattr(value, "password", None)

    if username is None and password is None:
        raise ValidationError(
            "Unsupported CalDAV credentials; expected None, "
            "a username/password mapping, a 2-item pair, "
            "or an object with username/password attributes."
        )

    if username is None or password is None:
        raise ValidationError(
            "CalDAV credentials require both username and password."
        )

    return {
        "username": str(username),
        "password": str(password),
    }


def _default_client_factory(**kwargs: Any) -> Any:
    """Import the replaceable library only inside the concrete adapter."""

    try:
        from caldav.davclient import DAVClient
    except ImportError as exc:
        raise UnavailableError(
            "Python package 'caldav' is not installed. "
            "Install the project dependencies first."
        ) from exc

    return DAVClient(**kwargs)


def _app_error(exc: Exception) -> Exception:
    """Map transport/library errors onto the frozen application errors."""

    if isinstance(
        exc,
        (
            AmbiguousError,
            ConflictError,
            NotFoundError,
            AssistantPermissionError,
            UnavailableError,
            ValidationError,
        ),
    ):
        return exc

    name = type(exc).__name__
    text = str(exc) or name

    if "NotFound" in name:
        return NotFoundError(text)

    if name in {
        "AuthorizationError",
        "AuthenticationError",
        "ForbiddenError",
        "UnauthorizedError",
    }:
        return AssistantPermissionError(text)

    if name in {
        "ETagMismatchError",
        "ScheduleTagMismatchError",
        "ConsistencyError",
    }:
        return ConflictError(text)

    if isinstance(exc, (TypeError, ValueError)):
        return ValidationError(text)

    return UnavailableError(text)


def _dt(value: Any) -> date | datetime | None:
    """Unwrap icalendar date/datetime values."""

    if value is None:
        return None

    return getattr(value, "dt", value)


def _text(value: Any) -> str:
    if value is None:
        return ""

    return str(value)


def _integer(value: Any) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _categories(value: Any) -> list[str]:
    if value is None:
        return []

    cats = getattr(value, "cats", None)

    if cats is not None:
        return [str(item) for item in cats]

    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]

    return [
        item.strip()
        for item in str(value).split(",")
        if item.strip()
    ]


def _component(resource: Any) -> Any:
    """Return the VEVENT/VTODO component for read-only mapping."""

    getter = getattr(
        resource,
        "get_icalendar_component",
        None,
    )

    if callable(getter):
        return getter()

    calendar = resource.get_icalendar_instance()

    for child in getattr(calendar, "subcomponents", ()):
        if getattr(child, "name", "") != "VTIMEZONE":
            return child

    raise ValidationError(
        "CalDAV object has no VEVENT/VTODO component."
    )


def _raw(resource: Any) -> Any:
    getter = getattr(resource, "get_data", None)

    if callable(getter):
        return getter()

    return getattr(resource, "data", None)


def _uid(resource: Any, component: Any) -> str:
    value = (
        getattr(resource, "id", None)
        or component.get("UID")
    )

    return _text(value)


def _overdue(
    due: date | datetime | None,
    completed: bool,
) -> bool:
    if completed or due is None:
        return False

    if isinstance(due, datetime):
        now = (
            datetime.now(due.tzinfo)
            if due.tzinfo
            else datetime.now()
        )

        return due < now

    return due < date.today()


def _same_day(
    value: date | datetime | None,
    target: date,
) -> bool:
    if value is None:
        return False

    if isinstance(value, datetime):
        return value.date() == target

    return value == target


def _matches(
    item: Task | Event,
    filters: Mapping[str, Any],
) -> bool:
    """Apply filters forwarded by TaskService/EventService."""

    for key, wanted in filters.items():
        if wanted is None:
            continue

        if key == "today":
            if not wanted:
                continue

            probe = item.start

            if isinstance(item, Task) and probe is None:
                probe = item.due

            if not _same_day(probe, date.today()):
                return False

            continue

        if key == "overdue" and isinstance(item, Task):
            if bool(item.overdue) != bool(wanted):
                return False

            continue

        if key in {"category", "categories"}:
            if isinstance(
                wanted,
                (list, tuple, set),
            ):
                wanted_set = {
                    str(value)
                    for value in wanted
                }
            else:
                wanted_set = {str(wanted)}

            if not wanted_set.intersection(
                set(item.categories)
            ):
                return False

            continue

        if not hasattr(item, key):
            raise ValidationError(
                f"Unsupported CalDAV filter: {key}"
            )

        if getattr(item, key) != wanted:
            return False

    return True


def _replace(
    component: Any,
    name: str,
    value: Any,
) -> None:
    """Replace one iCalendar property safely."""

    component.pop(name, None)

    if value is not None:
        component.add(name, value)


class LibraryCalDAVAdapter:
    """Full synchronous implementation of CalDAVAdapter."""

    def __init__(
        self,
        base_url_provider: BaseURLProvider,
        credentials: Any,
        *,
        client_factory: Callable[..., Any] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url_provider = base_url_provider
        self.credentials = credentials

        self._client_factory = (
            client_factory
            or _default_client_factory
        )

        self._timeout = timeout

        self._client: Any | None = None
        self._client_base_url: str | None = None

    @property
    def base_url(self) -> str:
        """Always obtain the current URL from ServerDiscovery."""

        return self._base_url_provider.get_base_url()

    def close(self) -> None:
        """Close the cached HTTP session."""

        client = self._client

        self._client = None
        self._client_base_url = None

        if client is not None:
            close = getattr(client, "close", None)

            if callable(close):
                close()

    def _new_client(
        self,
        base_url: str,
        credentials: Any,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "url": base_url,
            "timeout": self._timeout,

            # ServerDiscovery already owns RFC6764/mDNS discovery.
            "enable_rfc6764": False,

            # Local/legacy CalDAV may legitimately use plain HTTP.
            # This does NOT disable HTTPS certificate verification.
            "require_tls": False,
        }

        kwargs.update(
            _credentials(credentials)
        )

        return self._client_factory(**kwargs)

    def _client_now(self) -> Any:
        """Build/rebuild client when resolved Base URL changes."""

        url = self.base_url

        if (
            self._client is None
            or self._client_base_url != url
        ):
            self.close()

            self._client = self._new_client(
                url,
                self.credentials,
            )

            self._client_base_url = url

        return self._client

    @staticmethod
    def _collection_info(
        calendar: Any,
    ) -> dict[str, Any]:
        get_name = getattr(
            calendar,
            "get_display_name",
            None,
        )

        try:
            if callable(get_name):
                name = _text(get_name())
            else:
                name = _text(
                    getattr(
                        calendar,
                        "name",
                        "",
                    )
                )

        except Exception:
            name = _text(
                getattr(
                    calendar,
                    "name",
                    "",
                )
            )

        get_components = getattr(
            calendar,
            "get_supported_components",
            None,
        )

        if callable(get_components):
            components = list(
                get_components()
            )
        else:
            components = []

        url = _text(
            getattr(
                calendar,
                "url",
                "",
            )
        )

        calendar_id = (
            getattr(
                calendar,
                "id",
                None,
            )
            or url
        )

        return {
            "id": _text(calendar_id),
            "name": name,
            "url": url,
            "components": [
                str(value)
                for value in components
            ],
        }

    def _calendars(
        self,
        client: Any | None = None,
    ) -> list[Any]:
        client = (
            client
            or self._client_now()
        )

        principal = client.get_principal()

        return list(
            client.get_calendars(
                principal
            )
        )

    def _compatible(
        self,
        component_name: str,
    ) -> list[Any]:
        """Return collections capable of storing the component."""

        result: list[Any] = []

        for calendar in self._calendars():
            getter = getattr(
                calendar,
                "get_supported_components",
                None,
            )

            if callable(getter):
                supported = [
                    str(value).upper()
                    for value in getter()
                ]
            else:
                supported = [
                    "VEVENT",
                    "VTODO",
                    "VJOURNAL",
                ]

            if component_name.upper() in supported:
                result.append(calendar)

        return result

    @staticmethod
    def _attach(
        obj: Task | Event,
        resource: Any,
        calendar: Any,
    ) -> None:
        """Keep transport metadata private from the Public API."""

        setattr(
            obj,
            "_caldav_etag",
            getattr(
                resource,
                "etag",
                None,
            ),
        )

        setattr(
            obj,
            "_caldav_url",
            _text(
                getattr(
                    resource,
                    "url",
                    "",
                )
            ),
        )

        setattr(
            obj,
            "_caldav_collection_url",
            _text(
                getattr(
                    calendar,
                    "url",
                    "",
                )
            ),
        )

    def _to_task(
        self,
        resource: Any,
        calendar: Any,
    ) -> Task:
        component = _component(resource)

        due = _dt(
            component.get("DUE")
        )

        status = (
            _text(
                component.get("STATUS")
            )
            or "NEEDS-ACTION"
        )

        completed_at = _dt(
            component.get("COMPLETED")
        )

        percent = _integer(
            component.get(
                "PERCENT-COMPLETE"
            )
        )

        completed = (
            status.upper() == "COMPLETED"
            or completed_at is not None
            or percent == 100
        )

        task = Task(
            id=_uid(
                resource,
                component,
            ),
            summary=_text(
                component.get("SUMMARY")
            ),
            description=_text(
                component.get(
                    "DESCRIPTION"
                )
            ),
            start=_dt(
                component.get("DTSTART")
            ),
            due=due,
            status=status,
            completed=completed,
            completed_at=(
                completed_at
                if isinstance(
                    completed_at,
                    datetime,
                )
                else None
            ),
            priority=_integer(
                component.get("PRIORITY")
            ),
            categories=_categories(
                component.get("CATEGORIES")
            ),
            overdue=_overdue(
                due,
                completed,
            ),
            raw=_raw(resource),
        )

        self._attach(
            task,
            resource,
            calendar,
        )

        return task

    def _to_event(
        self,
        resource: Any,
        calendar: Any,
    ) -> Event:
        component = _component(resource)

        event = Event(
            id=_uid(
                resource,
                component,
            ),
            summary=_text(
                component.get("SUMMARY")
            ),
            start=_dt(
                component.get("DTSTART")
            ),
            end=_dt(
                component.get("DTEND")
            ),
            location=_text(
                component.get("LOCATION")
            ),
            description=_text(
                component.get(
                    "DESCRIPTION"
                )
            ),
            categories=_categories(
                component.get("CATEGORIES")
            ),
            raw=_raw(resource),
        )

        self._attach(
            event,
            resource,
            calendar,
        )

        return event

    def _find(
        self,
        uid: str,
        component_name: str,
    ) -> tuple[Any, Any]:
        """Find a UID without silently choosing among duplicates."""

        found: list[
            tuple[Any, Any]
        ] = []

        if component_name == "VTODO":
            getter_name = (
                "get_todo_by_uid"
            )
        else:
            getter_name = (
                "get_event_by_uid"
            )

        for calendar in self._compatible(
            component_name
        ):
            getter = getattr(
                calendar,
                getter_name,
            )

            try:
                resource = getter(uid)

            except Exception as exc:
                if (
                    "NotFound"
                    in type(exc).__name__
                ):
                    continue

                raise _app_error(
                    exc
                ) from exc

            found.append(
                (
                    resource,
                    calendar,
                )
            )

        if not found:
            raise NotFoundError(uid)

        if len(found) > 1:
            raise AmbiguousError(
                f"UID {uid!r} exists in "
                "more than one CalDAV collection."
            )

        return found[0]

    def _create_calendar(
        self,
        obj: Task | Event,
        component_name: str,
    ) -> Any:
        """Choose a collection without silently guessing."""

        calendars = self._compatible(
            component_name
        )

        wanted = getattr(
            obj,
            "_caldav_collection_url",
            None,
        )

        if wanted:
            matches = [
                calendar
                for calendar in calendars
                if _text(
                    getattr(
                        calendar,
                        "url",
                        "",
                    )
                )
                == _text(wanted)
            ]

            if len(matches) == 1:
                return matches[0]

            raise NotFoundError(
                "CalDAV collection "
                f"not found: {wanted}"
            )

        if not calendars:
            raise UnavailableError(
                "No CalDAV collection "
                f"supports {component_name}."
            )

        if len(calendars) > 1:
            raise AmbiguousError(
                "More than one CalDAV "
                f"collection supports "
                f"{component_name}; "
                "a collection must be "
                "selected before creating "
                "the object."
            )

        return calendars[0]

    @staticmethod
    def _check_etag(
        resource: Any,
        expected: str | None,
    ) -> None:
        if expected is None:
            return

        current = getattr(
            resource,
            "etag",
            None,
        )

        if current != expected:
            raise ConflictError(
                "CalDAV object changed "
                "on the server "
                f"(expected ETag "
                f"{expected!r}, "
                f"got {current!r})."
            )

    @staticmethod
    def _edit_task(
        resource: Any,
        changes: Mapping[str, Any],
    ) -> None:
        allowed = {
            "summary",
            "description",
            "start",
            "due",
            "status",
            "completed",
            "completed_at",
            "priority",
            "categories",
        }

        unknown = (
            set(changes)
            - allowed
        )

        if unknown:
            raise ValidationError(
                "Unsupported Task field(s): "
                + ", ".join(
                    sorted(unknown)
                )
            )

        if not changes:
            return

        with resource.edit_icalendar_component() as component:
            properties = {
                "summary": "SUMMARY",
                "description": "DESCRIPTION",
                "start": "DTSTART",
                "due": "DUE",
                "status": "STATUS",
                "priority": "PRIORITY",
                "categories": "CATEGORIES",
            }

            for field, prop in properties.items():
                if field in changes:
                    _replace(
                        component,
                        prop,
                        changes[field],
                    )

            if "completed_at" in changes:
                _replace(
                    component,
                    "COMPLETED",
                    changes[
                        "completed_at"
                    ],
                )

            if "completed" in changes:
                if bool(
                    changes["completed"]
                ):
                    if (
                        "status"
                        not in changes
                    ):
                        _replace(
                            component,
                            "STATUS",
                            "COMPLETED",
                        )

                    _replace(
                        component,
                        "PERCENT-COMPLETE",
                        100,
                    )

                    if (
                        "completed_at"
                        not in changes
                    ):
                        _replace(
                            component,
                            "COMPLETED",
                            datetime.now(
                            ).astimezone(),
                        )

                else:
                    component.pop(
                        "COMPLETED",
                        None,
                    )

                    _replace(
                        component,
                        "PERCENT-COMPLETE",
                        0,
                    )

                    if (
                        "status"
                        not in changes
                        and _text(
                            component.get(
                                "STATUS"
                            )
                        ).upper()
                        == "COMPLETED"
                    ):
                        _replace(
                            component,
                            "STATUS",
                            "NEEDS-ACTION",
                        )

            if (
                _text(
                    changes.get(
                        "status"
                    )
                ).upper()
                == "COMPLETED"
                and "completed"
                not in changes
            ):
                _replace(
                    component,
                    "PERCENT-COMPLETE",
                    100,
                )

                if (
                    component.get(
                        "COMPLETED"
                    )
                    is None
                ):
                    _replace(
                        component,
                        "COMPLETED",
                        datetime.now(
                        ).astimezone(),
                    )

    @staticmethod
    def _edit_event(
        resource: Any,
        changes: Mapping[str, Any],
    ) -> None:
        allowed = {
            "summary",
            "start",
            "end",
            "location",
            "description",
            "categories",
        }

        unknown = (
            set(changes)
            - allowed
        )

        if unknown:
            raise ValidationError(
                "Unsupported Event field(s): "
                + ", ".join(
                    sorted(unknown)
                )
            )

        if not changes:
            return

        with resource.edit_icalendar_component() as component:
            properties = {
                "summary": "SUMMARY",
                "start": "DTSTART",
                "end": "DTEND",
                "location": "LOCATION",
                "description": "DESCRIPTION",
                "categories": "CATEGORIES",
            }

            for field, prop in properties.items():
                if field in changes:
                    _replace(
                        component,
                        prop,
                        changes[field],
                    )

    # ------------------------------------------------------------
    # CalDAVAdapter implementation
    # ------------------------------------------------------------

    def discover(
        self,
        base_url: str,
        credentials: Any,
    ) -> dict[str, Any]:
        """Probe an explicit endpoint without changing settings."""

        client = None

        try:
            client = self._new_client(
                base_url,
                credentials,
            )

            principal = (
                client.get_principal()
            )

            calendars = list(
                client.get_calendars(
                    principal
                )
            )

            return {
                "base_url": base_url,
                "principal_url": _text(
                    getattr(
                        principal,
                        "url",
                        "",
                    )
                ),
                "collections": [
                    self._collection_info(
                        calendar
                    )
                    for calendar
                    in calendars
                ],
            }

        except Exception as exc:
            raise _app_error(
                exc
            ) from exc

        finally:
            if client is not None:
                close = getattr(
                    client,
                    "close",
                    None,
                )

                if callable(close):
                    close()

    def collections(
        self,
    ) -> Sequence[dict[str, Any]]:
        try:
            return [
                self._collection_info(
                    calendar
                )
                for calendar
                in self._calendars()
            ]

        except Exception as exc:
            raise _app_error(
                exc
            ) from exc

    def get_task(
        self,
        task_id: str,
    ) -> Task:
        try:
            resource, calendar = (
                self._find(
                    task_id,
                    "VTODO",
                )
            )

            return self._to_task(
                resource,
                calendar,
            )

        except Exception as exc:
            raise _app_error(
                exc
            ) from exc

    def list_tasks(
        self,
        **filters: Any,
    ) -> Sequence[Task]:
        try:
            result: list[Task] = []

            for calendar in self._compatible(
                "VTODO"
            ):
                resources = (
                    calendar.get_todos(
                        include_completed=True
                    )
                )

                for resource in resources:
                    task = self._to_task(
                        resource,
                        calendar,
                    )

                    if _matches(
                        task,
                        filters,
                    ):
                        result.append(
                            task
                        )

            return result

        except Exception as exc:
            raise _app_error(
                exc
            ) from exc

    def create_task(
        self,
        task: Task,
    ) -> Task:
        try:
            calendar = (
                self._create_calendar(
                    task,
                    "VTODO",
                )
            )

            kwargs: dict[str, Any] = {
                "summary": task.summary,
            }

            values = {
                "uid": (
                    task.id
                    or None
                ),
                "description": (
                    task.description
                    or None
                ),
                "dtstart": task.start,
                "due": task.due,
                "status": (
                    task.status
                    or None
                ),
                "priority": task.priority,
                "categories": (
                    task.categories
                    or None
                ),
            }

            for key, value in values.items():
                if value is not None:
                    kwargs[key] = value

            resource = (
                calendar.add_todo(
                    **kwargs
                )
            )

            if (
                task.completed
                or task.completed_at
                is not None
            ):
                self._edit_task(
                    resource,
                    {
                        "completed": True,
                        "completed_at": (
                            task.completed_at
                            or datetime.now(
                            ).astimezone()
                        ),
                        "status": "COMPLETED",
                    },
                )

                resource.save()

            return self._to_task(
                resource,
                calendar,
            )

        except Exception as exc:
            raise _app_error(
                exc
            ) from exc

    def update_task(
        self,
        task_id: str,
        changes: dict[str, Any],
        *,
        etag: str | None = None,
    ) -> Task:
        try:
            resource, calendar = (
                self._find(
                    task_id,
                    "VTODO",
                )
            )

            self._check_etag(
                resource,
                etag,
            )

            if changes:
                self._edit_task(
                    resource,
                    changes,
                )

                resource.save()

            return self._to_task(
                resource,
                calendar,
            )

        except Exception as exc:
            raise _app_error(
                exc
            ) from exc

    def delete_task(
        self,
        task_id: str,
        *,
        etag: str | None = None,
    ) -> None:
        try:
            resource, _calendar = (
                self._find(
                    task_id,
                    "VTODO",
                )
            )

            self._check_etag(
                resource,
                etag,
            )

            resource.delete()

        except Exception as exc:
            raise _app_error(
                exc
            ) from exc

    def get_event(
        self,
        event_id: str,
    ) -> Event:
        try:
            resource, calendar = (
                self._find(
                    event_id,
                    "VEVENT",
                )
            )

            return self._to_event(
                resource,
                calendar,
            )

        except Exception as exc:
            raise _app_error(
                exc
            ) from exc

    def list_events(
        self,
        **filters: Any,
    ) -> Sequence[Event]:
        try:
            result: list[Event] = []

            for calendar in self._compatible(
                "VEVENT"
            ):
                resources = (
                    calendar.get_events()
                )

                for resource in resources:
                    event = (
                        self._to_event(
                            resource,
                            calendar,
                        )
                    )

                    if _matches(
                        event,
                        filters,
                    ):
                        result.append(
                            event
                        )

            return result

        except Exception as exc:
            raise _app_error(
                exc
            ) from exc

    def create_event(
        self,
        event: Event,
    ) -> Event:
        try:
            calendar = (
                self._create_calendar(
                    event,
                    "VEVENT",
                )
            )

            kwargs: dict[str, Any] = {
                "summary": event.summary,
            }

            values = {
                "uid": (
                    event.id
                    or None
                ),
                "dtstart": event.start,
                "dtend": event.end,
                "location": (
                    event.location
                    or None
                ),
                "description": (
                    event.description
                    or None
                ),
                "categories": (
                    event.categories
                    or None
                ),
            }

            for key, value in values.items():
                if value is not None:
                    kwargs[key] = value

            resource = (
                calendar.add_event(
                    **kwargs
                )
            )

            return self._to_event(
                resource,
                calendar,
            )

        except Exception as exc:
            raise _app_error(
                exc
            ) from exc

    def update_event(
        self,
        event_id: str,
        changes: dict[str, Any],
        *,
        etag: str | None = None,
    ) -> Event:
        try:
            resource, calendar = (
                self._find(
                    event_id,
                    "VEVENT",
                )
            )

            self._check_etag(
                resource,
                etag,
            )

            if changes:
                self._edit_event(
                    resource,
                    changes,
                )

                resource.save()

            return self._to_event(
                resource,
                calendar,
            )

        except Exception as exc:
            raise _app_error(
                exc
            ) from exc

    def delete_event(
        self,
        event_id: str,
        *,
        etag: str | None = None,
    ) -> None:
        try:
            resource, _calendar = (
                self._find(
                    event_id,
                    "VEVENT",
                )
            )

            self._check_etag(
                resource,
                etag,
            )

            resource.delete()

        except Exception as exc:
            raise _app_error(
                exc
            ) from exc