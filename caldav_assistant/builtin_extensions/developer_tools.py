"""Small foreground debugging helpers for the interactive CLI.

This bundled extension deliberately keeps external programs outside Assistant Core.
Commands run only when the user explicitly invokes them, inherit the current terminal,
and return control to CalDAV Assistant when the child process exits.
"""
from __future__ import annotations

import os
import subprocess
import sys

from caldav_assistant.easy import command


_CLEAR_SEQUENCE = "\x1b[2J\x1b[H"


def _default_shell() -> str:
    """Return the user's normal interactive shell without permanently replacing CLI."""
    configured = os.environ.get("COMSPEC") if os.name == "nt" else os.environ.get("SHELL")
    if configured:
        return configured
    return "cmd.exe" if os.name == "nt" else "/bin/sh"


@command(
    "clear",
    aliases=("cls",),
    description="Clear the current terminal screen.",
)
def clear_screen() -> None:
    """Clear using ANSI instead of depending on an external `clear` executable."""
    sys.stdout.write(_CLEAR_SEQUENCE)
    sys.stdout.flush()


@command(
    "shell",
    aliases=("sh",),
    description="Temporarily run an external command or interactive shell for debugging.",
)
def run_external(*argv: str) -> int:
    """Run one foreground child process and return its exit code.

    Examples::

        shell git status
        shell pytest -q
        shell bash

    With no arguments the user's configured shell is started.  Typing ``exit`` in
    that shell returns to the CalDAV Assistant prompt.  ``shell=True`` is avoided so
    normal argument boundaries remain explicit; pipelines can still be requested as
    ``shell bash -lc \"...\"`` when needed.
    """
    command_argv = list(argv) if argv else [_default_shell()]
    try:
        return subprocess.run(command_argv, check=False).returncode
    except FileNotFoundError as exc:
        program = command_argv[0] if command_argv else ""
        raise ValueError(f"External command not found: {program}") from exc


__all__ = ["clear_screen", "run_external"]
