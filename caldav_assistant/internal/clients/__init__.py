"""Concrete client adapters for CalDAV Assistant.

Clients own transport/display concerns only. They must not own Task/Event business
rules or become an alternate source of truth.
"""

from .terminal import StdConsoleIO

__all__ = ["StdConsoleIO"]
