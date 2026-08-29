"""Scratch-like CLI Settings actions with production CalDAV setup.

Presentation/composition only:
CLI -> ctx.settings (RemoteSettingsAPI) -> RuntimeClient -> IPC -> service-side
CalDAVSetupService / PublicSettingsAPI.

This module never reads SQLite, credentials, CalDAV XML, or HTTP directly.
"""
from __future__ import annotations

import json
from typing import Any

from ...api.v1.errors import ValidationError
from ..commands.service import CommandService
from .keys import (
    CALDAV_BASE_URL,
    CALDAV_CREDENTIALS,
    CALDAV_EVENT_COLLECTION_URL,
    CALDAV_TASK_COLLECTION_URL,
    CALDAV_WORKLOG_COLLECTION_URL,
    EXTENSIONS_ENABLED,
)
from .schema import DEFAULT_SETTINGS_SCHEMA, SettingSpec


_CATEGORY_ORDER = (
    "Language",
    "CalDAV",
    "Notifications",
    "WordPress",
    "Commands",
    "Extensions",
)


def _display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "On" if value else "Off"
    if value is None:
        return "Not configured"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


class SettingsActions:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.schema = DEFAULT_SETTINGS_SCHEMA

    def _show(self, value: Any) -> None:
        show = getattr(self.ctx.ui, "show", None)
        if callable(show):
            show(value)

    def _choose(self, title: str, items: list[str]) -> str | None:
        choose = getattr(self.ctx.ui, "choose", None)
        if not callable(choose):
            raise ValidationError("Interactive settings require ctx.ui.choose()")
        return choose(title, items)

    def _ask_text(self, prompt: str) -> str | None:
        ask = getattr(self.ctx.ui, "ask_text", None)
        if not callable(ask):
            raise ValidationError("Interactive settings require ctx.ui.ask_text()")
        return ask(prompt)

    def _ask_secret(self, prompt: str) -> str | None:
        ask = getattr(self.ctx.ui, "ask_secret", None)
        if not callable(ask):
            raise ValidationError(
                "Interactive CalDAV credentials require ctx.ui.ask_secret()"
            )
        return ask(prompt)

    def _get(self, spec: SettingSpec) -> Any:
        if not spec.public_read:
            return None
        return self.ctx.settings.get(spec.key, spec.default_value())

    def _edit_spec(self, spec: SettingSpec) -> None:
        if not spec.public_write:
            raise ValidationError(f"{spec.key} is read-only")
        if spec.secret:
            raise ValidationError(
                f"{spec.key} must use its dedicated secure setup flow"
            )

        if spec.kind == "bool":
            selected = self._choose(spec.label, ["On", "Off"])
            if selected is None:
                return
            value: Any = selected == "On"
        elif spec.kind == "choice":
            selected = self._choose(spec.label, list(spec.choices))
            if selected is None:
                return
            value = selected
        else:
            value = self._ask_text(f"{spec.label}: ")
            if value is None:
                return

        normalized = self.ctx.settings.set(spec.key, value)
        self._show(f"✓ {spec.label}: {_display_value(normalized)}")

    def _extensions_panel(self) -> None:
        state = self.ctx.settings.get(EXTENSIONS_ENABLED, {})
        enabled = sorted(
            name for name, active in (state or {}).items() if bool(active)
        )
        lines = ["Extensions"]
        lines.append("Enabled: " + (", ".join(enabled) if enabled else "none"))
        lines.append(
            "Use `extensions` and `extension enable|disable|reload ...` "
            "for lifecycle management."
        )
        self._show("\n".join(lines))

    # ------------------------------------------------------------------
    # Production CalDAV setup (secret remains write-only)
    # ------------------------------------------------------------------
    def _caldav_status(self) -> dict[str, Any]:
        method = getattr(self.ctx.settings, "caldav_status", None)
        if callable(method):
            value = method()
            return dict(value) if isinstance(value, dict) else {}

        base_url = self.ctx.settings.get(CALDAV_BASE_URL, None)
        return {
            "base_url": base_url,
            "base_url_configured": bool(base_url),
            "credentials_configured": False,
        }

    def _set_caldav_server(self, value: str | None = None) -> Any:
        if value is None:
            value = self._ask_text("CalDAV server: ")
        if value is None:
            return None
        method = getattr(self.ctx.settings, "set_caldav_base_url", None)
        if callable(method):
            result = method(value)
        else:
            normalized = self.ctx.settings.set(CALDAV_BASE_URL, value)
            result = {"base_url": normalized, "base_url_configured": True}
        self._show(f"✓ CalDAV server: {result.get('base_url', value)}")
        return result

    def _set_caldav_credentials(self) -> Any:
        username = self._ask_text("Username: ")
        if username is None:
            return None
        password = self._ask_secret("Password")
        if password is None:
            return None

        method = getattr(self.ctx.settings, "set_caldav_credentials", None)
        if callable(method):
            result = method(username, password)
        else:
            self.ctx.settings.set(
                CALDAV_CREDENTIALS,
                {"username": username, "password": password},
            )
            result = {"credentials_configured": True}

        self._show("✓ CalDAV credentials configured.")
        return result

    def _clear_caldav_credentials(self) -> Any:
        method = getattr(self.ctx.settings, "clear_caldav_credentials", None)
        if callable(method):
            result = method()
        else:
            reset = getattr(self.ctx.settings, "reset", None)
            if callable(reset):
                reset(CALDAV_CREDENTIALS)
            else:
                self.ctx.settings.set(CALDAV_CREDENTIALS, None)
            result = {"credentials_configured": False}
        self._show("✓ CalDAV credentials cleared.")
        return result

    def _test_caldav_connection(self) -> Any:
        method = getattr(self.ctx.settings, "test_caldav_connection", None)
        if not callable(method):
            raise ValidationError(
                "CalDAV connection test requires the production Runtime bridge"
            )
        result = method()
        count = result.get("collection_count", 0) if isinstance(result, dict) else 0
        self._show(f"✓ CalDAV connection: {count} collection(s)")
        return result

    def _caldav_collections(self) -> list[Any]:
        method = getattr(self.ctx.settings, "caldav_collections", None)
        if not callable(method):
            raise ValidationError(
                "CalDAV collection discovery requires the production Runtime bridge"
            )
        return list(method() or [])

    @staticmethod
    def _collection_name(item: Any) -> str:
        if not isinstance(item, dict):
            return str(item)
        return str(
            item.get("name")
            or item.get("display_name")
            or item.get("url")
            or item.get("href")
            or item
        )

    @staticmethod
    def _collection_url(item: Any) -> str | None:
        if not isinstance(item, dict):
            return None
        value = item.get("url") or item.get("href") or item.get("id")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _collection_components(item: Any) -> tuple[str, ...]:
        if not isinstance(item, dict):
            return ()
        raw = item.get("components") or item.get("supported_components") or ()
        return tuple(str(value).upper() for value in raw)

    def _show_caldav_collections(self) -> Any:
        items = self._caldav_collections()
        lines = ["CalDAV collections"]
        if not items:
            lines.append("(none)")
        for index, item in enumerate(items, 1):
            name = self._collection_name(item)
            components = self._collection_components(item)
            suffix = " [" + ", ".join(components) + "]" if components else ""
            lines.append(f"{index}. {name}{suffix}")
        self._show("\n".join(lines))
        return items

    def _role_name(self, url: Any, items: list[Any]) -> str:
        if not url:
            return "Not configured"
        wanted = str(url)
        for item in items:
            if self._collection_url(item) == wanted:
                return self._collection_name(item)
        return "Unavailable collection"

    def _choose_collection_role(
        self,
        title: str,
        key: str,
        component: str,
        items: list[Any],
    ) -> Any:
        compatible = [
            item
            for item in items
            if component.upper() in self._collection_components(item)
            and self._collection_url(item)
        ]
        if not compatible:
            self._show(f"No discovered collection supports {component.upper()}.")
            return None

        labels: list[str] = []
        mapping: dict[str, str] = {}
        for index, item in enumerate(compatible, 1):
            components = self._collection_components(item)
            suffix = " [" + ", ".join(components) + "]" if components else ""
            label = f"{index}. {self._collection_name(item)}{suffix}"
            labels.append(label)
            mapping[label] = str(self._collection_url(item))

        selected = self._choose(title, labels)
        if selected is None:
            return None
        url = mapping.get(selected)
        if not url:
            raise ValidationError("Unknown collection selection")
        value = self.ctx.settings.set(key, url)
        name = self._collection_name(
            next(item for item in compatible if self._collection_url(item) == url)
        )
        self._show(f"✓ {title}: {name}")
        return value

    def _collection_roles_panel(self) -> None:
        while True:
            items = self._caldav_collections()
            if not items:
                self._show("No CalDAV collections were found. Test the connection first.")
                return

            task_url = self.ctx.settings.get(CALDAV_TASK_COLLECTION_URL, None)
            event_url = self.ctx.settings.get(CALDAV_EVENT_COLLECTION_URL, None)
            work_url = self.ctx.settings.get(CALDAV_WORKLOG_COLLECTION_URL, None)
            task_label = f"Default task collection: {self._role_name(task_url, items)}"
            event_label = f"Default event collection: {self._role_name(event_url, items)}"
            work_label = f"Work log collection: {self._role_name(work_url, items)}"

            selected = self._choose(
                "Collection roles",
                [task_label, event_label, work_label, "Show collections"],
            )
            if selected is None:
                return
            if selected == task_label:
                self._choose_collection_role(
                    "Default task collection",
                    CALDAV_TASK_COLLECTION_URL,
                    "VTODO",
                    items,
                )
            elif selected == event_label:
                self._choose_collection_role(
                    "Default event collection",
                    CALDAV_EVENT_COLLECTION_URL,
                    "VEVENT",
                    items,
                )
            elif selected == work_label:
                self._choose_collection_role(
                    "Work log collection",
                    CALDAV_WORKLOG_COLLECTION_URL,
                    "VEVENT",
                    items,
                )
            elif selected == "Show collections":
                self._show_caldav_collections()

    def _use_discovered_server(
        self,
        status: dict[str, Any] | None = None,
    ) -> Any:
        status = status or self._caldav_status()
        candidates = [
            str(item)
            for item in (status.get("discovered_candidates") or [])
            if str(item).strip()
        ]
        if not candidates:
            self._show("No CalDAV servers were discovered.")
            return None
        if len(candidates) == 1:
            selected = candidates[0]
        else:
            selected = self._choose("Choose CalDAV server", candidates)
            if selected is None:
                return None
        return self._set_caldav_server(str(selected))

    def _caldav_panel(self) -> None:
        while True:
            status = self._caldav_status()
            server = status.get("base_url") or "Not configured"
            credentials = (
                "Configured"
                if status.get("credentials_configured")
                else "Not configured"
            )
            labels = [f"CalDAV server: {server}"]
            if status.get("discovered_candidates"):
                labels.append("Use discovered server")
            labels.extend(
                [
                    f"CalDAV credentials: {credentials}",
                    "Test connection",
                    "Collection roles",
                    "Collections",
                    "Clear credentials",
                ]
            )

            selected = self._choose("CalDAV", labels)
            if selected is None:
                return
            if selected == f"CalDAV server: {server}":
                self._set_caldav_server()
            elif selected == "Use discovered server":
                self._use_discovered_server(status)
            elif selected == f"CalDAV credentials: {credentials}":
                self._set_caldav_credentials()
            elif selected == "Test connection":
                self._test_caldav_connection()
            elif selected == "Collection roles":
                self._collection_roles_panel()
            elif selected == "Collections":
                self._show_caldav_collections()
            elif selected == "Clear credentials":
                self._clear_caldav_credentials()

    def _category(self, category: str) -> None:
        if category == "CalDAV":
            self._caldav_panel()
            return
        if category == "Extensions":
            self._extensions_panel()
            return

        specs = [
            spec
            for spec in self.schema.list(category=category)
            if getattr(spec, "interactive", True) and spec.public_write
        ]
        if not specs:
            self._show(f"No editable settings in {category}.")
            return

        while True:
            labels: list[str] = []
            mapping: dict[str, SettingSpec] = {}
            for spec in specs:
                current = self._get(spec) if spec.public_read else "Hidden"
                label = f"{spec.label}: {_display_value(current)}"
                labels.append(label)
                mapping[label] = spec

            selected = self._choose(category, labels)
            if selected is None:
                return
            spec = mapping.get(selected)
            if spec is None:
                raise ValidationError("Unknown settings menu selection")
            self._edit_spec(spec)

    def interactive(self) -> None:
        while True:
            selected = self._choose("Settings", list(_CATEGORY_ORDER))
            if selected is None:
                return None
            self._category(selected)

    menu = interactive

    # ------------------------------------------------------------------
    # One-shot Settings API
    # ------------------------------------------------------------------
    @staticmethod
    def _usage() -> str:
        return (
            "settings\n"
            "settings categories\n"
            "settings list [CATEGORY]\n"
            "settings get KEY\n"
            "settings set KEY VALUE\n"
            "settings reset KEY\n"
            "settings caldav status|test|collections|roles\n"
            "settings caldav server URL\n"
            "settings caldav credentials\n"
            "settings caldav clear-credentials"
        )

    def list_settings(self, category: str | None = None) -> str:
        items = self.ctx.settings.list(category)
        return "\n".join(
            f"{item['key']} = {_display_value(item.get('value'))}"
            for item in items
        )

    def get_setting(self, key: str) -> str:
        spec = self.schema.get(key)
        if spec.secret or not spec.public_read:
            raise ValidationError(f"Setting {spec.key!r} is not publicly readable")
        return f"{spec.key} = {_display_value(self.ctx.settings.get(spec.key))}"

    def set_setting(self, key: str, value: Any) -> str:
        spec = self.schema.get(key)
        if spec.secret:
            raise ValidationError(
                "Do not put secrets on the command line; "
                "use `settings caldav credentials` interactively."
            )
        normalized = self.ctx.settings.set(spec.key, value)
        return f"✓ {spec.key} = {_display_value(normalized)}"

    def reset_setting(self, key: str) -> str:
        spec = self.schema.get(key)
        if not spec.public_write:
            raise ValidationError(f"Setting {spec.key!r} is read-only")
        if spec.key == CALDAV_CREDENTIALS:
            self._clear_caldav_credentials()
            return f"✓ {spec.key} = <hidden>"
        reset = getattr(self.ctx.settings, "reset", None)
        if callable(reset):
            normalized = reset(spec.key)
        else:
            normalized = self.ctx.settings.set(spec.key, spec.default_value())
        return f"✓ {spec.key} = {_display_value(normalized)}"

    def _caldav_command(self, *parts: Any) -> Any:
        if not parts:
            return self._caldav_panel()
        action = str(parts[0]).strip().casefold()
        if action == "status":
            return self._caldav_status()
        if action == "test":
            return self._test_caldav_connection()
        if action in {"collections", "list"}:
            return self._show_caldav_collections()
        if action in {"roles", "collection-roles"}:
            if len(parts) != 1:
                raise ValidationError("settings caldav roles takes no arguments")
            return self._collection_roles_panel()
        if action == "server":
            if len(parts) != 2:
                raise ValidationError("settings caldav server requires one URL")
            return self._set_caldav_server(str(parts[1]))
        if action in {"credentials", "auth"}:
            if len(parts) != 1:
                raise ValidationError(
                    "Do not put credentials on the command line; "
                    "use this action interactively."
                )
            return self._set_caldav_credentials()
        if action in {"clear-credentials", "clear-auth"}:
            return self._clear_caldav_credentials()
        raise ValidationError(f"Unknown CalDAV settings action: {parts[0]}")

    def settings(self, *parts: Any) -> Any:
        if not parts:
            return self.interactive()
        if not all(isinstance(part, str) for part in parts):
            raise ValidationError("settings arguments must be text")

        action = parts[0].strip().casefold()
        if action in {"help", "?"}:
            return self._usage()
        if action == "caldav":
            return self._caldav_command(*parts[1:])
        if action == "categories":
            if len(parts) != 1:
                raise ValidationError("settings categories takes no arguments")
            return "\n".join(_CATEGORY_ORDER)
        if action == "list":
            if len(parts) > 2:
                raise ValidationError("settings list accepts at most one category")
            return self.list_settings(parts[1] if len(parts) == 2 else None)
        if action == "get":
            if len(parts) != 2:
                raise ValidationError("settings get requires one key")
            return self.get_setting(parts[1])
        if action == "set":
            if len(parts) < 3:
                raise ValidationError("settings set requires KEY VALUE")
            return self.set_setting(parts[1], " ".join(parts[2:]))
        if action == "reset":
            if len(parts) != 2:
                raise ValidationError("settings reset requires one key")
            return self.reset_setting(parts[1])
        raise ValidationError(f"Unknown settings action: {parts[0]}")

    command = settings


def register_settings_cli_command(
    commands: CommandService,
    ctx: Any,
) -> SettingsActions:
    actions = SettingsActions(ctx)
    registry = commands.registry
    contains = getattr(registry, "contains", None)
    exists = contains("settings") if callable(contains) else ("settings" in registry)
    if not exists:
        register = getattr(commands, "register_builtin", None)
        if callable(register):
            register(
                "settings",
                actions.settings,
                description="Open or modify Assistant settings.",
            )
        else:
            registry.register(
                "settings",
                actions.settings,
                protected=True,
                description="Open or modify Assistant settings.",
            )
    return actions


__all__ = ["SettingsActions", "register_settings_cli_command"]
