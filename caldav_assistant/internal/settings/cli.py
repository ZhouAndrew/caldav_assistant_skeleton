"""Scratch-like CLI Settings actions with production CalDAV setup.

Presentation/composition only:
CLI -> ctx.settings (RemoteSettingsAPI) -> RuntimeClient -> IPC -> service-side
CalDAVSetupService / PublicSettingsAPI.

Settings panels that manage another subsystem (Commands/Extensions) dispatch through
the same CommandService used by the top-level CLI. They are real management surfaces,
not informational shells and not a second implementation of those subsystems.

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
    EXPERIMENTAL_FAST_QUERY_CACHE,
)
from .schema import DEFAULT_SETTINGS_SCHEMA, SettingSpec


_CATEGORY_ORDER = (
    "Language",
    "CalDAV",
    "Notifications",
    "WordPress",
    "Commands",
    "Extensions",
    "Experimental",
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

    def _run_command(self, name: str, *parts: str) -> Any:
        commands = getattr(self.ctx, "commands", None)
        run = getattr(commands, "run", None)
        if not callable(run):
            raise ValidationError(
                f"{name} management requires the normal CommandService"
            )
        return run(name, *parts)

    def _show_command_result(self, name: str, *parts: str) -> Any:
        result = self._run_command(name, *parts)
        if result is not None:
            self._show(result)
        return result

    def _ask_extension_name(self, action: str) -> str | None:
        value = self._ask_text(f"Extension name for {action}")
        if value is None:
            return None
        clean = str(value).strip()
        if not clean:
            raise ValidationError("Extension name must not be empty")
        return clean

    def _extensions_panel(self) -> None:
        """Manage the real ExtensionManager through its canonical CLI commands."""
        while True:
            selected = self._choose(
                "Extensions",
                [
                    "Show extensions",
                    "Enable extension",
                    "Disable extension",
                    "Reload extension",
                    "Extension errors",
                    "Create user extension",
                    "Extension guide",
                ],
            )
            if selected is None:
                return
            if selected == "Show extensions":
                self._show_command_result("extensions")
                continue
            if selected == "Extension guide":
                self._show_command_result("extension", "guide")
                continue
            if selected == "Extension errors":
                name = self._ask_text("Extension name (empty = all)")
                clean = str(name or "").strip()
                self._show_command_result("extension", "errors", *([clean] if clean else []))
                continue
            if selected == "Create user extension":
                name = self._ask_extension_name("create")
                if name is not None:
                    self._show_command_result("extension", "new", name)
                continue

            verb = {
                "Enable extension": "enable",
                "Disable extension": "disable",
                "Reload extension": "reload",
            }.get(selected)
            if verb is None:
                raise ValidationError("Unknown Extensions menu selection")
            name = self._ask_extension_name(verb)
            if name is not None:
                self._show_command_result("extension", verb, name)

    def _commands_panel(self) -> None:
        """Browse the actual CommandRegistry instead of pretending ASCII is editable."""
        while True:
            selected = self._choose(
                "Commands",
                [
                    "Show available commands",
                    "Explain a command",
                    "Canonical command language: ASCII English (fixed)",
                ],
            )
            if selected is None:
                return
            if selected == "Show available commands":
                self._show_command_result("help")
            elif selected == "Explain a command":
                name = self._ask_text("Command name")
                if name is not None and str(name).strip():
                    self._show_command_result("help", str(name).strip())
            else:
                self._show(
                    "Canonical command names remain ASCII English by the frozen v1 contract.\n"
                    "UI language is independent; aliases/extensions may add other entry points."
                )

    # ------------------------------------------------------------------
    # Experimental cache diagnostics (CLI-internal Runtime bridge)
    # ------------------------------------------------------------------
    def _cache_status(self) -> dict[str, Any]:
        method = getattr(self.ctx.settings, "_experimental_cache_status", None)
        if not callable(method):
            raise ValidationError(
                "Cache diagnostics require the production Runtime bridge"
            )
        value = method()
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _format_cache_status(status: dict[str, Any]) -> str:
        enabled = "On" if status.get("enabled") else "Off"
        available = bool(status.get("snapshot_available"))
        lines = ["Experimental cache", f"Fast query cache: {enabled}"]
        if available:
            lines.append(
                "Snapshot: Available "
                f"({status.get('task_count', 0)} task(s), "
                f"{status.get('event_count', 0)} event(s))"
            )
            lines.append(
                "Verified from CalDAV: "
                + str(status.get("synced_at") or "Unknown")
            )
            if status.get("cache_updated_at"):
                reason = status.get("cache_update_reason") or "local update"
                lines.append(
                    "Local cache update: "
                    f"{status.get('cache_updated_at')} ({reason})"
                )
        else:
            lines.append("Snapshot: Not available")

        sync_status = status.get("sync_status")
        if isinstance(sync_status, dict):
            state = str(sync_status.get("state") or "unknown")
            if state == "error":
                error_type = str(sync_status.get("error_type") or "Error")
                error = str(sync_status.get("error") or "Unknown error")
                failed_at = sync_status.get("failed_at")
                suffix = f" at {failed_at}" if failed_at else ""
                lines.append(f"Last sync: ERROR{suffix} — {error_type}: {error}")
            else:
                mode = sync_status.get("effective_mode") or sync_status.get("requested_mode")
                suffix = f" ({mode})" if mode else ""
                lines.append(f"Last sync: {state.upper()}{suffix}")

        counts = status.get("read_counts")
        if isinstance(counts, dict):
            lines.append(
                "Reads since background service start: "
                f"cache={int(counts.get('cache', 0) or 0)}, "
                f"CalDAV={int(counts.get('caldav', 0) or 0)}"
            )

        recent = status.get("recent_reads")
        if isinstance(recent, list) and recent:
            lines.append("Recent reads:")
            for item in recent[-6:]:
                if not isinstance(item, dict):
                    continue
                operation = item.get("operation") or "read"
                source = item.get("source") or "unknown"
                reason = item.get("reason") or "unknown"
                lines.append(f"  {operation} → {source} ({reason})")
        else:
            lines.append("Recent reads: none yet")

        return "\n".join(lines)

    def cache_status_text(self) -> str:
        return self._format_cache_status(self._cache_status())

    def _refresh_cache(self) -> dict[str, Any]:
        method = getattr(self.ctx.settings, "_experimental_cache_refresh", None)
        if not callable(method):
            raise ValidationError(
                "Cache refresh requires the production Runtime bridge"
            )
        value = method()
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _format_refresh_result(result: dict[str, Any]) -> str:
        return (
            "✓ Cache refreshed from authoritative CalDAV: "
            f"{result.get('task_count', 0)} task(s), "
            f"{result.get('event_count', 0)} event(s)."
        )

    def _experimental_panel(self) -> None:
        spec = self.schema.get(EXPERIMENTAL_FAST_QUERY_CACHE)
        while True:
            current = self._get(spec)
            toggle_label = f"{spec.label}: {_display_value(current)}"
            selected = self._choose(
                "Experimental",
                [
                    toggle_label,
                    "Cache status",
                    "Refresh cache now",
                    "How this works",
                ],
            )
            if selected is None:
                return
            if selected == toggle_label:
                self._edit_spec(spec)
            elif selected == "Cache status":
                self._show(self.cache_status_text())
            elif selected == "Refresh cache now":
                self._show(self._format_refresh_result(self._refresh_cache()))
            elif selected == "How this works":
                self._show(
                    "The fast query cache is experimental and defaults to Off.\n"
                    "CalDAV remains the Task/Event source of truth.\n"
                    "When On, reads may use the last verified local snapshot.\n"
                    "Cache misses fall back to CalDAV. Writes always go to CalDAV first.\n"
                    "Turning it Off restores direct CalDAV reads."
                )

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
        if category == "Commands":
            self._commands_panel()
            return
        if category == "Extensions":
            self._extensions_panel()
            return
        if category == "Experimental":
            self._experimental_panel()
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
            "settings caldav clear-credentials\n"
            "settings cache status|refresh\n"
            "settings extensions [list|enable|disable|reload|errors|new|guide] [NAME]\n"
            "settings commands [COMMAND]"
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

    def _cache_command(self, *parts: Any) -> str:
        if not parts:
            return self.cache_status_text()
        if len(parts) != 1:
            raise ValidationError("settings cache accepts status or refresh")
        action = str(parts[0]).strip().casefold()
        if action == "status":
            return self.cache_status_text()
        if action == "refresh":
            return self._format_refresh_result(self._refresh_cache())
        raise ValidationError(f"Unknown cache settings action: {parts[0]}")

    def _extensions_command(self, *parts: Any) -> Any:
        if not parts:
            return self._extensions_panel()
        action = str(parts[0]).strip().casefold()
        if action in {"list", "show"}:
            if len(parts) != 1:
                raise ValidationError("settings extensions list takes no name")
            return self._run_command("extensions")
        if action in {"guide", "errors"} and len(parts) == 1:
            return self._run_command("extension", action)
        if action in {"enable", "disable", "reload", "errors", "new"} and len(parts) == 2:
            return self._run_command("extension", action, str(parts[1]))
        raise ValidationError(
            "settings extensions expects list|enable|disable|reload|errors|new|guide [NAME]"
        )

    def _commands_command(self, *parts: Any) -> Any:
        if not parts:
            return self._run_command("help")
        if len(parts) != 1:
            raise ValidationError("settings commands accepts at most one command name")
        return self._run_command("help", str(parts[0]))

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
        if action == "cache":
            return self._cache_command(*parts[1:])
        if action in {"extensions", "extension"}:
            return self._extensions_command(*parts[1:])
        if action in {"commands", "command"}:
            return self._commands_command(*parts[1:])
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
