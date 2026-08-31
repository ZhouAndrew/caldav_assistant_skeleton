"""Terminal reminder bell helper.

This module is presentation/infrastructure only.  It does not decide when a reminder
is due and it does not read settings itself.  Callers pass an already-normalized bell
pattern, which keeps timing policy out of the terminal I/O details.
"""
from __future__ import annotations

from time import sleep
from typing import Any, Callable


def ring_terminal_bell(
    console_io: Any,
    *,
    repeat_count: int = 1,
    interval_ms: int = 0,
    sleep_fn: Callable[[float], None] = sleep,
) -> int:
    """Ring the terminal bell a readable number of times with a visible interval.

    A short interval matters because many terminal emulators coalesce adjacent BEL
    characters.  Returning the number of attempted rings makes this helper easy to
    test without inventing reminder business state.
    """
    terminal_bell_repeat_count = max(0, int(repeat_count))
    terminal_bell_interval_ms = max(0, int(interval_ms))
    interval_seconds = terminal_bell_interval_ms / 1000.0

    terminal_stream = getattr(console_io, "stdout", None)
    stream_write = getattr(terminal_stream, "write", None)
    stream_flush = getattr(terminal_stream, "flush", None)
    fallback_write = getattr(console_io, "write", None)

    for ring_number in range(terminal_bell_repeat_count):
        if callable(stream_write):
            stream_write("\a")
            if callable(stream_flush):
                stream_flush()
        elif callable(fallback_write):
            fallback_write("\a")
        else:
            break

        is_last_ring = ring_number + 1 >= terminal_bell_repeat_count
        if not is_last_ring and interval_seconds > 0:
            sleep_fn(interval_seconds)

    return terminal_bell_repeat_count


__all__ = ["ring_terminal_bell"]
