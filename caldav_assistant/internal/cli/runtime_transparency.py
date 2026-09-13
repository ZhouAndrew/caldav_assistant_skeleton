"""Keep CLI performance work visible instead of hiding the runtime structure."""
from __future__ import annotations

from typing import Any


def install(module: Any) -> None:
    """Expose the read path, preserve unknown!=empty, and contain menu Ctrl-C."""
    if bool(getattr(module, "_runtime_transparency_installed", False)):
        return

    conversation = module.conversation
    original_read_snapshot = module._read_snapshot
    original_snapshot_text = conversation._snapshot_text
    original_home_menu = conversation._home_menu

    def transparent_read_snapshot(app: Any):
        conversation._show(
            app,
            "Path: CLI → Local IPC → AgendaService → CalDAV "
            "[Tasks ∥ Events ∥ Work].",
        )
        conversation._show(
            app,
            "Primary source: live CalDAV; independent reads run in parallel. "
            "If the interactive deadline is missed, the last verified snapshot is "
            "shown only with an explicit stale warning.",
        )
        return original_read_snapshot(app)

    def truthful_snapshot_text(snapshot: Any) -> str:
        if getattr(snapshot, "warning", None):
            hours = getattr(snapshot, "window_hours", 24)
            return (
                f"Upcoming · next {hours}h\n"
                "  Live Task/Event state is unavailable (unknown, not empty)."
            )
        return original_snapshot_text(snapshot)

    def interrupt_safe_home_menu(app: Any, snapshot: Any):
        try:
            return original_home_menu(app, snapshot)
        except KeyboardInterrupt:
            conversation._show(app, "")
            conversation._show(
                app,
                "^C Menu cancelled → returning to console. No Task/Event state changed.",
            )
            return "console"

    module._read_snapshot = transparent_read_snapshot
    conversation._snapshot_text = truthful_snapshot_text
    conversation._home_menu = interrupt_safe_home_menu
    module._runtime_transparency_installed = True


__all__ = ["install"]
