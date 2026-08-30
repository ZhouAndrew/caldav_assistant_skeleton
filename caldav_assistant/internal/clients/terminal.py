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
from typing import Any, Callable, TextIO


class StdConsoleIO:
    """Tiny line-oriented console adapter shared by REPL, Menu and PromptKit.

    ``push_line()`` is a presentation-only pushback primitive. It lets a nested
    navigation menu hand an arbitrary line back to the ordinary REPL parser instead
    of swallowing it as an invalid menu choice.
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

    def push_line(self, value: Any) -> None:
        """Make one line the next value returned by ``read()`` without parsing it."""
        self._pending_lines.appendleft(str(value))

    def read(self, prompt: str = "") -> str:
        if self._pending_lines:
            return self._pending_lines.popleft()
        reader = self._input_fn or input
        return reader(prompt)

    def write(self, value: Any = "") -> None:
        print(value, file=self.stdout, flush=True)

    def error(self, value: Any) -> None:
        print(value, file=self.stderr, flush=True)

    prompt = read
    input = read
    output = write
    show = write
