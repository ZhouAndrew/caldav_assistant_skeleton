"""Contain Ctrl-C across the whole installed Waiting Mode lifecycle.

conversation_live already handles Ctrl-C inside its steady-state loop.  A user can,
however, press Ctrl-C immediately after "Waiting Mode" is printed while the initial
work-period/session reads are still running.  This composition guard closes that
small pre-loop gap without changing Task/CalDAV semantics.
"""
from __future__ import annotations

from typing import Any


def install(module: Any) -> None:
    """Route any leaked Waiting Mode KeyboardInterrupt to the normal Task menu."""
    if bool(getattr(module, "_waiting_interrupt_guard_installed", False)):
        return

    original_waiting_mode = module._waiting_mode

    def guarded_waiting_mode(app: Any) -> str:
        while True:
            try:
                return original_waiting_mode(app)
            except KeyboardInterrupt:
                target = module.legacy._monitor_target(app)
                if target is None or target.kind != "task" or not target.current_work:
                    module.conversation._show(app, "")
                    return "console"
                action = module.conversation._wait_interrupt(app, target)
                if action != "wait":
                    return action
                # The user chose Continue waiting. Re-enter the normal Waiting Mode
                # setup and then its existing steady-state loop.

    module._waiting_mode = guarded_waiting_mode
    module._waiting_interrupt_guard_installed = True


__all__ = ["install"]
