"""CLI browser for the actual stable Public Python API.

This module is presentation-only.  The authoritative inventory lives in the public
``caldav_assistant.api`` catalog and is generated from real exports/Protocols rather
than a second hand-maintained interface list.
"""
from __future__ import annotations

from typing import Any

from ...api import APIEntry, api_catalog, api_describe, api_exists, api_find
from ...api.v1.errors import AmbiguousError, NotFoundError, ValidationError


def _joined(parts: tuple[Any, ...], *, label: str) -> str:
    if not parts or not all(isinstance(part, str) for part in parts):
        raise ValidationError(f"{label} must not be empty")
    value = " ".join(part.strip() for part in parts if part.strip()).strip()
    if not value:
        raise ValidationError(f"{label} must not be empty")
    return value


def _brief(entry: APIEntry) -> str:
    signature = entry.signature if entry.kind in {"callable", "method", "class"} else ""
    summary = f" — {entry.summary}" if entry.summary else ""
    return f"{entry.path}{signature}{summary}"


def _details(entry: APIEntry) -> str:
    signature = entry.signature or "-"
    usage = entry.usage or entry.path
    return (
        f"{entry.path}\n"
        f"  exists: yes\n"
        f"  layer: {entry.layer}\n"
        f"  kind: {entry.kind}\n"
        f"  signature: {signature}\n"
        f"  source: {entry.source}\n"
        f"  {entry.summary}\n"
        f"\nUsage:\n{usage}"
    )


class APIHelpAction:
    """Small query action behind the protected ``api`` CLI command."""

    def __call__(self, *parts: Any) -> str:
        if not parts:
            counts = {
                layer: len(api_catalog(layer))
                for layer in ("easy", "object", "full")
            }
            return (
                "Public Python API browser\n"
                f"  Easy API: {counts['easy']} interfaces\n"
                f"  Object API: {counts['object']} interfaces\n"
                f"  Full v1 API: {counts['full']} interfaces\n"
                "\n"
                "Commands:\n"
                "  api <interface>          show signature and usage\n"
                "  api exists <interface>   check whether it really exists\n"
                "  api search <text>        search public interfaces\n"
                "  api list [easy|object|full]\n"
                "\n"
                "Examples:\n"
                "  api easy.complete\n"
                "  api ctx.tasks.complete\n"
                "  api exists Task.start_task\n"
                "  api search reminder"
            )

        verb = str(parts[0]).strip().casefold()
        rest = tuple(parts[1:])

        if verb == "exists":
            name = _joined(rest, label="Interface")
            return f"{'YES' if api_exists(name) else 'NO'} — {name}"

        if verb == "search":
            query = _joined(rest, label="Search text")
            matches = api_find(query)
            if not matches:
                return f"No public API interfaces match: {query}"
            return "Public API matches:\n" + "\n".join(f"  {_brief(entry)}" for entry in matches)

        if verb == "list":
            if len(rest) > 1:
                raise ValidationError("Usage: api list [easy|object|full]")
            layer = str(rest[0]).strip() if rest else None
            try:
                entries = api_catalog(layer)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            heading = f"Public API ({layer})" if layer else "Public API"
            return heading + ":\n" + "\n".join(f"  {_brief(entry)}" for entry in entries)

        if verb == "show":
            name = _joined(rest, label="Interface")
        else:
            name = _joined(parts, label="Interface")

        try:
            return _details(api_describe(name))
        except AmbiguousError:
            candidates = [
                entry
                for entry in api_find(name)
                if entry.path.rsplit(".", 1)[-1].casefold() == name.casefold()
            ]
            if not candidates:
                raise
            return (
                f"Ambiguous public API name: {name}\n"
                "Use one full path:\n"
                + "\n".join(f"  {_brief(entry)}" for entry in candidates)
            )
        except NotFoundError:
            suggestions = api_find(name)
            if suggestions:
                return (
                    f"Public API interface does not exist exactly: {name}\n"
                    "Related interfaces:\n"
                    + "\n".join(f"  {_brief(entry)}" for entry in suggestions[:20])
                )
            return f"NO — public API interface not found: {name}"


def register_api_cli_command(commands: Any) -> None:
    """Register the protected API browser without creating another dispatcher."""

    if "api" in commands.registry:
        return
    commands.register_builtin(
        "api",
        APIHelpAction(),
        description="Browse Public Python API interfaces, signatures, existence, and usage.",
    )


__all__ = ["APIHelpAction", "register_api_cli_command"]
