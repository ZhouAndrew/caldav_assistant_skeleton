"""Schema and validators for Assistant settings."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from string import Formatter
from typing import Any, Callable

from ...api.v1.errors import NotFoundError, ValidationError
from .keys import *


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be non-empty text")
    return value.strip()


def _optional_text(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be text")
    clean = value.strip()
    return clean or None


def _boolean(value: Any, *, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        clean = value.strip().casefold()
        if clean in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
            return True
        if clean in {"0", "false", "no", "n", "off", "disable", "disabled"}:
            return False
    raise ValidationError(f"{label} must be on/off or true/false")


def _integer_range(value: Any, *, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be a whole number")
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a whole number") from exc
    if number < minimum or number > maximum:
        raise ValidationError(f"{label} must be between {minimum} and {maximum}")
    return number


def _locale(value: Any) -> str:
    clean = _text(value, label="UI locale").replace("_", "-").casefold()
    if clean in {"en", "en-us", "en-gb"}:
        return "en"
    if clean in {"zh", "zh-cn", "zh-hans", "zh-sg"}:
        return "zh-CN"
    raise ValidationError("UI locale must be en or zh-CN")


def _command_language(value: Any) -> str:
    clean = _text(value, label="Command language").casefold()
    if clean not in {"en", "ascii"}:
        raise ValidationError("Canonical command language must remain ASCII English")
    return "en"


def _url(value: Any) -> str | None:
    if value is None:
        return None
    clean = _text(value, label="CalDAV base URL")
    if not (clean.startswith("http://") or clean.startswith("https://")):
        raise ValidationError("CalDAV base URL must use http:// or https://")
    return clean.rstrip("/")


def _optional_path(value: Any) -> str | None:
    return _optional_text(value, label="WordPress path")


def _collection_url(value: Any) -> str | None:
    return _optional_text(value, label="CalDAV collection")


def _credentials(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError("CalDAV credentials must be a mapping")
    allowed = {"username", "password"}
    unknown = set(value) - allowed
    if unknown:
        raise ValidationError("Unsupported CalDAV credential fields")
    result = {}
    for key, item in value.items():
        if not isinstance(item, str):
            raise ValidationError(f"{key} must be text")
        result[key] = item
    return result


def _extension_map(value: Any) -> dict[str, bool]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError("extensions.enabled must be a mapping")
    result = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValidationError("Extension names must be text")
        result[key.strip()] = _boolean(item, label=f"Extension {key}")
    return result


def _worklog_style(value: Any) -> str:
    clean = _text(value, label="WordPress work-log style").casefold()
    allowed = {"off", "compact", "detailed", "custom"}
    if clean not in allowed:
        raise ValidationError("WordPress work-log style must be off, compact, detailed, or custom")
    return clean


def _worklog_template(value: Any) -> str:
    clean = _text(value, label="WordPress work-log template")
    allowed = {
        "start",
        "end",
        "task",
        "uid",
        "duration",
        "duration_minutes",
        "status",
        "start_iso",
        "end_iso",
    }
    try:
        fields = [name for _, name, _, _ in Formatter().parse(clean) if name]
    except ValueError as exc:
        raise ValidationError("WordPress work-log template has invalid braces") from exc
    unknown = {name for name in fields if name not in allowed}
    if unknown:
        raise ValidationError(
            "Unknown WordPress work-log template field(s): " + ", ".join(sorted(unknown))
        )
    return clean


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    label: str
    category: str
    kind: str
    default: Any = None
    public_read: bool = True
    public_write: bool = True
    choices: tuple[str, ...] = ()
    secret: bool = False
    validator: Callable[[Any], Any] | None = None

    def normalize(self, value: Any) -> Any:
        return self.validator(value) if self.validator else deepcopy(value)

    def default_value(self) -> Any:
        return deepcopy(self.default)

    def metadata(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "kind": self.kind,
            "default": self.default_value(),
            "public_read": self.public_read,
            "public_write": self.public_write,
            "choices": list(self.choices),
            "secret": self.secret,
        }


class SettingsSchema:
    def __init__(self, specs):
        self._specs = {spec.key: spec for spec in specs}

    def find(self, key):
        return self._specs.get(key)

    def get(self, key):
        try:
            return self._specs[key]
        except KeyError as exc:
            raise NotFoundError(key) from exc

    def list(self, category=None):
        return tuple(
            spec
            for spec in self._specs.values()
            if category is None or spec.category == category
        )

    def categories(self):
        seen = []
        for spec in self._specs.values():
            if spec.category not in seen:
                seen.append(spec.category)
        return tuple(seen)


DEFAULT_SETTINGS_SCHEMA = SettingsSchema([
    SettingSpec(UI_LOCALE, "Language", "Language", "choice", "en", choices=("en", "zh-CN"), validator=_locale),
    SettingSpec(CALDAV_BASE_URL, "CalDAV server", "CalDAV", "text", None, validator=_url),
    SettingSpec(CALDAV_CREDENTIALS, "CalDAV credentials", "CalDAV", "secret", None, public_read=False, public_write=True, secret=True, validator=_credentials),
    SettingSpec(CALDAV_TASK_COLLECTION_URL, "Default task collection", "CalDAV", "text", None, validator=_collection_url),
    SettingSpec(CALDAV_EVENT_COLLECTION_URL, "Default event collection", "CalDAV", "text", None, validator=_collection_url),
    SettingSpec(CALDAV_WORKLOG_COLLECTION_URL, "Work log collection", "CalDAV", "text", None, validator=_collection_url),
    SettingSpec(NOTIFICATIONS_ENABLED, "Notifications", "Notifications", "bool", True, validator=lambda v: _boolean(v, label="Notifications")),
    SettingSpec(NOTIFICATION_SOUND_ENABLED, "Reminder sound", "Notifications", "bool", True, validator=lambda v: _boolean(v, label="Reminder sound")),
    SettingSpec(TERMINAL_BELL_ENABLED, "Terminal bell", "Notifications", "bool", True, validator=lambda v: _boolean(v, label="Terminal bell")),
    SettingSpec(
        TERMINAL_BELL_REPEAT_COUNT,
        "Terminal bell rings per reminder",
        "Notifications",
        "choice",
        3,
        choices=("1", "2", "3", "4", "5", "8", "10"),
        validator=lambda v: _integer_range(
            v,
            label="Terminal bell repeat count",
            minimum=1,
            maximum=10,
        ),
    ),
    SettingSpec(
        TERMINAL_BELL_INTERVAL_MS,
        "Pause between bell rings (ms)",
        "Notifications",
        "choice",
        400,
        choices=("100", "200", "300", "400", "500", "750", "1000", "1500", "2000"),
        validator=lambda v: _integer_range(
            v,
            label="Terminal bell interval",
            minimum=100,
            maximum=2000,
        ),
    ),
    SettingSpec(WORDPRESS_ENABLED, "WordPress", "WordPress", "bool", True, validator=lambda v: _boolean(v, label="WordPress")),
    SettingSpec(WORDPRESS_PATH, "WordPress path", "WordPress", "text", None, validator=_optional_path),
    SettingSpec(WORDPRESS_WORKLOG_STYLE, "Work-log style", "WordPress", "choice", "compact", choices=("off", "compact", "detailed", "custom"), validator=_worklog_style),
    SettingSpec(WORDPRESS_WORKLOG_TEMPLATE, "Custom work-log template", "WordPress", "text", "{start}-{end} {task}", validator=_worklog_template),
    SettingSpec(COMMAND_LANGUAGE, "Command language", "Commands", "choice", "en", choices=("en",), validator=_command_language),
    SettingSpec(EXTENSIONS_ENABLED, "Extensions", "Extensions", "mapping", {}, validator=_extension_map),
    SettingSpec(
        AGENDA_UPCOMING_HOURS,
        "Upcoming window (hours)",
        "Agenda",
        "text",
        24,
        validator=lambda v: _integer_range(
            v,
            label="Upcoming window",
            minimum=1,
            maximum=744,
        ),
    ),
    SettingSpec(
        EXPERIMENTAL_FAST_QUERY_CACHE,
        "Fast query cache (experimental)",
        "Experimental",
        "bool",
        False,
        validator=lambda v: _boolean(v, label="Fast query cache")),
])

__all__ = ["SettingSpec", "SettingsSchema", "DEFAULT_SETTINGS_SCHEMA"]
