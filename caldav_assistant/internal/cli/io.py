"""Minimal replaceable console I/O adapter.

MODULE CONTRACT
- Imports/calls: stdlib terminal streams only.
- Provides: ``StdConsoleIO``.
- Must not: parse commands, know Task/Event business rules, access Core services,
  CalDAV, SQLite, IPC, or localization policy.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, TextIO


class StdConsoleIO:
    """Tiny line-oriented console adapter shared by REPL, Menu and PromptKit."""

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

    def read(self, prompt: str = "") -> str:
        reader = self._input_fn or input
        return reader(prompt)

    def write(self, value: Any = "") -> None:
        print(value, file=self.stdout, flush=True)

    def error(self, value: Any) -> None:
        print(value, file=self.stderr, flush=True)

    # Compatibility aliases for small Prompt/Menu implementations.
    prompt = read
    input = read
    output = write
    show = write
