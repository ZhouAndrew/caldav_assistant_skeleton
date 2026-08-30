"""Compatibility import for the terminal client I/O adapter.

The concrete implementation now lives in ``internal.clients.terminal`` so the CLI
is explicitly a client of the Assistant rather than the owner of console I/O.
Internal callers using the historical path continue to work.
"""

from ..clients.terminal import StdConsoleIO

__all__ = ["StdConsoleIO"]
