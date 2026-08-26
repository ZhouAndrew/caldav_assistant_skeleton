"""CLI one-shot + conversational REPL wiring.

MODULE CONTRACT
- Imports/calls: bootstrap CLI composition root, CommandService, PromptKit/UI, stdlib.
- Provides: ``run_cli()``, ``run_repl()``, ``run_one_shot()``, ``main()``.
- Must not: instantiate TaskService/EventService/CalDAVAdapter, access CalDAV XML,
  SQLite tables, OS notification APIs, or duplicate Core business rules.

Both one-shot and REPL input terminate at the same ``CommandService.run()`` entry point.
"""
from __future__ import annotations

from dataclasses import dataclass
import shlex
import sys
from typing import Any, Sequence

from ...api.v1.errors import CalDAVAssistantError, NotFoundError
from ..bootstrap import build_cli_application
from .actions import EXIT_REPL, register_cli_builtin_commands


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    raw: str
    name: str
    args: tuple[str, ...]


def parse_command_line(text: str) -> ParsedCommand | None:
    """Parse REPL text only; command meaning is resolved by CommandRegistry."""
    if not isinstance(text, str):
        raise TypeError("CLI input must be text")
    raw = text.strip()
    if not raw:
        return None

    parts = shlex.split(raw)
    if not parts:
        return None
    return ParsedCommand(raw=raw, name=parts[0], args=tuple(parts[1:]))


def _ui_show(app: Any, value: Any) -> None:
    show = getattr(app.ctx.ui, "show", None)
    if callable(show):
        show(value)
        return
    write = getattr(app.io, "write", None)
    if callable(write):
        write(value)


def _error(app: Any, message: str) -> None:
    error = getattr(app.io, "error", None)
    if callable(error):
        error(message)
        return
    _ui_show(app, message)


def _render_result(app: Any, result: Any) -> None:
    if result is None or result is EXIT_REPL:
        return

    # ActionResult is intentionally duck-typed here so CLI remains a presentation
    # boundary rather than importing every domain model.
    if hasattr(result, "success") and hasattr(result, "affected"):
        success = bool(getattr(result, "success"))
        message = str(getattr(result, "message", "") or "").strip()
        affected = getattr(result, "affected", None)

        if message:
            _ui_show(app, ("✓ " if success else "✗ ") + message)
            return

        if affected is not None:
            label = getattr(affected, "summary", None) or getattr(affected, "id", None)
            if label:
                _ui_show(app, ("✓ " if success else "✗ ") + str(label))
                return

        _ui_show(app, "✓ Done." if success else "✗ Operation failed.")
        return

    _ui_show(app, result)


def _execute(app: Any, parsed: ParsedCommand) -> tuple[int, bool]:
    """Execute one already-parsed command through CommandService only."""
    try:
        entry = app.commands.resolve(parsed.name)
    except NotFoundError:
        _error(app, f"Unknown command: {parsed.name}. Type 'help' for commands.")
        return 2, False
    except CalDAVAssistantError as exc:
        _error(app, f"{type(exc).__name__}: {exc}")
        return 2, False

    # Transparent interpretation is compact for simple/low-risk commands.
    if parsed.name.casefold() != entry.name.casefold():
        _ui_show(app, f"Command → {entry.name}")

    try:
        result = app.commands.run(entry.name, *parsed.args)
    except KeyboardInterrupt:
        _error(app, "Cancelled.")
        return 130, False
    except EOFError:
        return 0, True
    except CalDAVAssistantError as exc:
        _error(app, f"{type(exc).__name__}: {exc}")
        return 2, False
    except (TypeError, ValueError) as exc:
        # Bad CLI arguments are recoverable input errors, not a REPL crash.
        _error(app, f"Invalid input: {exc}")
        return 2, False
    except Exception as exc:
        # The CLI boundary keeps the session alive while still making unexpected
        # failures visible. CommandService itself deliberately does not swallow them.
        _error(app, f"{type(exc).__name__}: {exc}")
        return 1, False

    if result is EXIT_REPL:
        return 0, True

    _render_result(app, result)
    return 0, False


def run_one_shot(app: Any, argv: Sequence[str]) -> int:
    if not argv:
        return 0

    name = str(argv[0]).strip()
    if not name:
        _error(app, "Command must not be empty.")
        return 2

    parsed = ParsedCommand(
        raw=" ".join(str(item) for item in argv),
        name=name,
        args=tuple(str(item) for item in argv[1:]),
    )
    code, _ = _execute(app, parsed)
    return code


def run_repl(app: Any) -> int:
    _ui_show(app, "CalDAV Assistant")
    _ui_show(app, "Type 'help' for commands. Ctrl-D or Ctrl-C exits.")

    last_code = 0
    while True:
        try:
            line = app.io.read("> ")
        except EOFError:
            _ui_show(app, "")
            return last_code
        except KeyboardInterrupt:
            _ui_show(app, "")
            return 130

        try:
            parsed = parse_command_line(line)
        except ValueError as exc:
            _error(app, f"Invalid input: {exc}")
            last_code = 2
            continue

        if parsed is None:
            continue

        code, should_exit = _execute(app, parsed)
        last_code = code
        if should_exit:
            return code


def run_cli(argv: Sequence[str] | None = None, *, app: Any = None) -> int:
    """Run one-shot when argv has a command; otherwise start the line REPL."""
    if argv is None:
        argv = sys.argv[1:]
    if app is None:
        app = build_cli_application()

    # The original bootstrap already registers a subset (today/next/done/edit-due).
    # Fill the remaining frozen core CLI commands into that exact same registry.
    register_cli_builtin_commands(app.commands, app.ctx)

    if argv:
        return run_one_shot(app, argv)
    return run_repl(app)


def main() -> int:
    return run_cli()


__all__ = [
    "ParsedCommand",
    "parse_command_line",
    "run_one_shot",
    "run_repl",
    "run_cli",
    "main",
]
