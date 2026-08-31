"""Terminal client I/O adapter.

MODULE CONTRACT
- Imports/calls: stdlib terminal streams only.
- Provides: ``StdConsoleIO``.
- Must not: parse commands, know Task/Event business rules, access Core services,
  CalDAV, SQLite, IPC, or localization policy.
"""
from __future__ import annotations

from collections import deque
import sys
from threading import Event
from typing import Any, Callable, TextIO


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
    """

    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self._input_fn = input_fn
        self.stdout = stdout or sys.stdout
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
