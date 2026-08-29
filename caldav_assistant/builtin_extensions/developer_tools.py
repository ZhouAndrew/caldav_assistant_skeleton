"""Opt-in terminal/debugging helpers for CalDAV Assistant.

External programs stay outside Assistant Core. ``shell`` preserves the original
foreground-only debugging behaviour. ``run`` is the explicit process launcher and can
start either a foreground child or a detached background child. Neither path uses
``shell=True``: argument boundaries remain explicit and pipelines still require the user
to opt into a real shell such as ``bash -lc``.

Detached background output is preserved in a per-user log file rather than discarded,
so starting a process in the background does not make its diagnostics disappear.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import BinaryIO, Sequence

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
    return ValueError(
        f"External command not found or not directly executable: {program}. "
        "If this is a shell built-in, pipeline, or redirection, run it through an "
        "explicit shell such as: run bash -lc \"...\""
    )


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


def _background_log() -> tuple[BinaryIO, Path]:
    """Create a persistent per-user log, falling back to the system temp directory."""
    preferred = Path.home() / ".caldav-assistant" / "run-logs"
    roots = (preferred, Path(tempfile.gettempdir()) / "caldav-assistant-run-logs")
    last_error: OSError | None = None
    for root in roots:
        try:
            root.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="w+b",
                prefix="run-",
                suffix=".log",
                dir=root,
                delete=False,
            )
            return handle, Path(handle.name)
        except OSError as exc:
            last_error = exc
    assert last_error is not None
    raise ValueError(f"Cannot create background command log: {last_error}") from last_error


def _start_background(command_argv: Sequence[str]) -> tuple[int, Path]:
    """Start one detached child and return its PID plus persistent output-log path."""
    log_handle, log_path = _background_log()
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
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
        try:
            log_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise _missing_program(command_argv, exc) from exc
    finally:
        log_handle.close()
    return int(process.pid), log_path


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

    With no arguments the user's configured shell is started. Typing ``exit`` in that
    shell returns to the CalDAV Assistant prompt.
    """
    command_argv = list(argv) if argv else [_default_shell()]
    return _run_foreground(command_argv)


@command(
    "run",
    description=(
        "Run an external command; append 'in background' or use -b/--background "
        "to detach it and preserve output in a log."
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

    Shell built-ins/pipelines/redirection are not guessed. Request a shell explicitly::

        run bash -lc "printf hello | sed s/hello/world/"

    ``run`` intentionally requires a command. Use ``shell`` with no arguments when an
    interactive shell is desired; an interactive shell is not meaningful once detached
    from stdin/stdout.
    """
    if not argv:
        raise ValueError(
            "run requires an external command; use 'shell' for an interactive shell"
        )

    command_argv, background = _background_args(argv)
    if background:
        pid, log_path = _start_background(command_argv)
        return (
            f"Started in background (PID {pid}): {' '.join(command_argv)}\n"
            f"Output log: {log_path}"
        )

    code = _run_foreground(command_argv)
    return f"Command exited with code {code}."


__all__ = [
    "clear_screen",
    "run_external",
    "run_command",
]
