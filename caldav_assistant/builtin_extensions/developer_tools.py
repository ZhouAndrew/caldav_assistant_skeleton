"""Opt-in terminal/debugging helpers for CalDAV Assistant.

External programs stay outside Assistant Core.  ``shell`` preserves the original
foreground-only debugging behaviour.  ``run`` is the explicit process launcher and can
start either a foreground child or a detached background child.  Neither path uses
``shell=True``: argument boundaries remain explicit and pipelines still require the user
to opt into a real shell such as ``bash -lc``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Sequence

from caldav_assistant.easy import command


_CLEAR_SEQUENCE = "\x1b[2J\x1b[H"
_BACKGROUND_SUFFIX = ("in", "background")
_BACKGROUND_FLAGS = {"--background", "-b"}


def _default_shell() -> str:
    """Return the user's normal interactive shell without permanently replacing CLI."""
    configured = os.environ.get("COMSPEC") if os.name == "nt" else os.environ.get("SHELL")
    if configured:
        return configured
    return "cmd.exe" if os.name == "nt" else "/bin/sh"


def _missing_program(command_argv: Sequence[str], exc: FileNotFoundError) -> ValueError:
    program = command_argv[0] if command_argv else ""
    return ValueError(f"External command not found: {program}")


def _background_args(argv: Sequence[str]) -> tuple[list[str], bool]:
    """Parse the human ``in background`` suffix plus script-friendly ``-b`` form."""
    parts = list(argv)
    background = False

    if parts and parts[0].casefold() in _BACKGROUND_FLAGS:
        background = True
        parts = parts[1:]
    elif len(parts) >= 2 and tuple(part.casefold() for part in parts[-2:]) == _BACKGROUND_SUFFIX:
        background = True
        parts = parts[:-2]

    if background and not parts:
        raise ValueError("Background mode requires an external command")
    return parts, background


def _start_background(command_argv: Sequence[str]) -> int:
    """Start one detached child and return its PID without keeping CLI attached."""
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(list(command_argv), **kwargs)
    except FileNotFoundError as exc:
        raise _missing_program(command_argv, exc) from exc
    return int(process.pid)


def _run_foreground(command_argv: Sequence[str]) -> int:
    try:
        return subprocess.run(list(command_argv), check=False).returncode
    except FileNotFoundError as exc:
        raise _missing_program(command_argv, exc) from exc


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
    description="Temporarily run an external command or interactive shell in foreground.",
)
def run_external(*argv: str) -> int:
    """Preserve the original foreground-only developer shell command.

    Examples::

        shell git status
        shell pytest -q
        shell bash

    With no arguments the user's configured shell is started.  Typing ``exit`` in that
    shell returns to the CalDAV Assistant prompt.
    """
    command_argv = list(argv) if argv else [_default_shell()]
    return _run_foreground(command_argv)


@command(
    "run",
    description=(
        "Run an external command; append 'in background' or use -b/--background "
        "to detach it."
    ),
)
def run_command(*argv: str):
    """Run an explicit external command in foreground or detached background mode.

    Human-friendly form::

        run python worker.py in background

    Script-friendly equivalents::

        run --background python worker.py
        run -b python worker.py

    Foreground form::

        run git status

    ``run`` intentionally requires a command.  Use ``shell`` with no arguments when an
    interactive shell is desired; an interactive shell is not meaningful once detached
    from stdin/stdout.
    """
    if not argv:
        raise ValueError(
            "run requires an external command; use 'shell' for an interactive shell"
        )

    command_argv, background = _background_args(argv)
    if background:
        pid = _start_background(command_argv)
        return f"Started in background (PID {pid}): {' '.join(command_argv)}"

    code = _run_foreground(command_argv)
    return f"Command exited with code {code}."


__all__ = [
    "clear_screen",
    "run_external",
    "run_command",
]
