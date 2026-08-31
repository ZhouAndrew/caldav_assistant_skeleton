"""Terminal client I/O adapter.

MODULE CONTRACT
- Imports/calls: stdlib terminal streams and injected presentation callables only.
- Provides: ``StdConsoleIO`` and ``TerminalBellProfile``.
- Must not: parse commands, know Task/Event business rules, access Core services,
  CalDAV, SQLite, IPC, or localization policy.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import sys
from threading import Event
from time import sleep
from typing import Any, Callable, TextIO


@dataclass(frozen=True, slots=True)
class TerminalBellProfile:
    """Injected presentation policy for one logical terminal reminder bell."""

    enabled: Callable[[], bool]
    repeat_count: Callable[[], int]
    interval_ms: Callable[[], int]


class _BellAwareTextStream:
    """Transparent stream wrapper that turns one BEL into a persistent reminder alarm.

    ``repeat_count`` is the number of rings in one burst. Bursts repeat until the
    human presses Ctrl-C. The Ctrl-C is consumed here: acknowledging the alarm must
    not accidentally pause, complete, or otherwise mutate the current Task.
    """

    def __init__(
        self,
        stream: TextIO,
        profile: TerminalBellProfile,
        *,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self._stream = stream
        self._profile = profile
        self._sleep_fn = sleep_fn

    @staticmethod
    def _read_setting(provider: Callable[[], Any], default: Any) -> Any:
        try:
            return provider()
        except Exception:
            return default

    def _ring_once_logically(self) -> int:
        """Ring in configured bursts until Ctrl-C acknowledges this reminder."""
        terminal_bell_enabled = bool(
            self._read_setting(self._profile.enabled, True)
        )
        if not terminal_bell_enabled:
            return 0

        try:
            rings_per_burst = max(
                1,
                int(self._read_setting(self._profile.repeat_count, 3)),
            )
        except (TypeError, ValueError):
            rings_per_burst = 3
        try:
            pause_between_rings_ms = max(
                100,
                int(self._read_setting(self._profile.interval_ms, 400)),
            )
        except (TypeError, ValueError):
            pause_between_rings_ms = 400

        pause_between_rings_seconds = pause_between_rings_ms / 1000.0
        pause_between_bursts_seconds = max(
            0.8,
            pause_between_rings_seconds * 2.0,
        )
        rings_sounded = 0

        self._stream.write("\n🔔 Reminder alarm — press Ctrl-C to stop the ringing.\n")
        self._stream.flush()
        try:
            while True:
                for ring_number in range(rings_per_burst):
                    self._stream.write("\a")
                    self._stream.flush()
                    rings_sounded += 1
                    is_last_ring_in_burst = ring_number + 1 >= rings_per_burst
                    if not is_last_ring_in_burst:
                        self._sleep_fn(pause_between_rings_seconds)
                self._sleep_fn(pause_between_bursts_seconds)
        except KeyboardInterrupt:
            self._stream.write("\n✓ Reminder alarm stopped. Task/Event state was not changed.\n")
            self._stream.flush()
            return rings_sounded

    def write(self, value: str) -> int:
        text = str(value)
        if "\a" not in text:
            return self._stream.write(text)

        text_parts = text.split("\a")
        for part_number, text_part in enumerate(text_parts):
            if text_part:
                self._stream.write(text_part)
            has_bell_after_part = part_number + 1 < len(text_parts)
            if has_bell_after_part:
                self._ring_once_logically()
        return len(text)

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class StdConsoleIO:
    """Tiny line-oriented console adapter shared by REPL, Menu and PromptKit.

    ``push_line()`` is a presentation-only pushback primitive. It lets a nested
    navigation menu hand an arbitrary line back to the ordinary REPL parser instead
    of swallowing it as an invalid menu choice.

    ``waiting_for_input`` is presentation state, not application state.  It allows a
    live-progress renderer to distinguish "Core is still working" from "the program
    has already displayed a menu and is waiting for the human".  Without this bit a
    worker-hosted prompt produced endless fake ``Still working`` heartbeats while the
    user was simply deciding what to choose.

    A ``TerminalBellProfile`` may be injected by the composition root. The rest of
    the CLI emits one ordinary ``\\a`` for one logical reminder. This adapter turns
    that logical alert into repeated, human-configured bell bursts and keeps repeating
    them until Ctrl-C acknowledges the reminder. Acknowledgement is presentation-only
    and deliberately does not become a Task/Event lifecycle command.
    """

    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        terminal_bell_profile: TerminalBellProfile | None = None,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self._input_fn = input_fn
        output_stream = stdout or sys.stdout
        self.stdout = (
            _BellAwareTextStream(
                output_stream,
                terminal_bell_profile,
                sleep_fn=sleep_fn,
            )
            if terminal_bell_profile is not None
            else output_stream
        )
        self.stderr = stderr or sys.stderr
        self._pending_lines: deque[str] = deque()
        self._input_wait = Event()

    @property
    def waiting_for_input(self) -> bool:
        return self._input_wait.is_set()

    def push_line(self, value: Any) -> None:
        """Make one line the next value returned by ``read()`` without parsing it."""
        self._pending_lines.appendleft(str(value))

    def read(self, prompt: str = "") -> str:
        if self._pending_lines:
            return self._pending_lines.popleft()
        reader = self._input_fn or input
        self._input_wait.set()
        try:
            return reader(prompt)
        finally:
            self._input_wait.clear()

    def write(self, value: Any = "") -> None:
        print(value, file=self.stdout, flush=True)

    def error(self, value: Any) -> None:
        print(value, file=self.stderr, flush=True)

    prompt = read
    input = read
    output = write
    show = write


__all__ = ["StdConsoleIO", "TerminalBellProfile"]
