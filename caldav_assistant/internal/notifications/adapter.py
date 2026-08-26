"""Operating-system notification boundary.

MODULE CONTRACT
- Imports: typing only.
- Calls: nothing concrete.
- Provides: ``NotificationAdapter`` protocol.
- Must not: contain Reminder/Task/Event business rules, CLI I/O, SQLite access,
  or platform-specific notification code.

Reminder/other application services depend on this contract.  Concrete Linux,
macOS and Windows implementations live in ``platform_adapters.py`` and are selected
only by the composition root (bootstrap).
"""
from __future__ import annotations

from typing import Any, Protocol


class NotificationAdapter(Protocol):
    """Replaceable boundary for one operating-system notification."""

    def notify(
        self,
        title: str,
        body: str = "",
        actions: Any = None,
    ) -> None:
        """Deliver a notification or raise a stable application error."""
        ...
