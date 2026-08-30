"""CLI one-shot + conversational REPL wiring.

MODULE CONTRACT
- Imports/calls: bootstrap CLI composition root, CommandService, PromptKit/UI, stdlib.
- Provides: ``run_cli()``, ``run_repl()``, ``run_one_shot()``, ``main()``.
- Must not: instantiate TaskService/EventService/CalDAVAdapter, access CalDAV XML,
  SQLite tables, OS notification APIs, or duplicate Core business rules.

Both one-shot and REPL input terminate at the same ``CommandService.run()`` entry point.
An empty interactive line is a discoverability affordance: when the guided ``menu``
command exists, Enter opens it. This means a new user can operate the program using
numbers without first learning command vocabulary; experienced users retain the
same direct-command path.
"""
from __future__ import annotations

from dataclasses import dataclass
import shlex
import sys
from typing import Any, Sequence

from ...api.v1.errors import CalDAVAssistantError, NotFoundError, ValidationError
from ...api.v1.models import Agenda, AgendaItem, Event, Task
from .actions import EXIT_REPL, register_cli_builtin_commands
from .api_help import register_api_cli_command
from .completion import completion_session
from .crud import register_crud_cli_commands
from .navigation import register_navigation_cli_commands
from .presenter import emit_agenda, emit_lines, render_lines
from ..extensions.availability import find_extension_command_support
from ..extensions.cli import register_extension_cli_commands
from ..settings.cli import register_settings_cli_command
from ..runtime.cli import register_background_cli_command
from ..undo.cli import register_undo_cli_command


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    raw: str
    name: str
    args: tuple[str, ...]


def _t(app: Any, key: str, default: str, **values: Any) -> str:
    translate = getattr(app.ctx.ui, "t", None)
    if callable(translate):
        return translate(key, default=default, **values)
    try:
        return default.format(**values)
    except Exception:
        return default


def parse_command_line(text: str) -> ParsedCommand | None:
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


def _unsupported_command_message(app: Any, command: str) -> str:
    support = find_extension_command_support(getattr(app, "extensions", None), command)
    if support is None:
        return _t(
            app,
            "cli.unsupported_command",
            "Unsupported command: {command}. Type 'help' for available commands.",
            command=command,
        )

    if support.status == "missing":
        return _t(
            app,
            "cli.command_supported_extension_missing",
            "Command '{command}' is supported by official extension '{extension}', "
            "but that extension is not installed in this build.",
            command=support.command,
            extension=support.extension,
        )
    if not support.enabled or support.status == "disabled":
        return _t(
            app,
            "cli.command_supported_extension_disabled",
            "Command '{command}' is supported, but extension '{extension}' is disabled. "
            "Enable it with: extension enable {extension}",
            command=support.command,
            extension=support.extension,
        )
    if support.status == "error":
        return _t(
            app,
            "cli.command_supported_extension_error",
            "Command '{command}' is supported by extension '{extension}', but the extension "
            "failed to load. Check: extension errors {extension}",
            command=support.command,
            extension=support.extension,
        )
    return _t(
        app,
        "cli.command_supported_extension_unavailable",
        "Command '{command}' is supported by extension '{extension}', but is not available "
        "right now. Try: extension reload {extension}",
        command=support.command,
        extension=support.extension,
    )


def _remember_result(app: Any, result: Any) -> None:
    """Keep the visible CLI context promised by the frozen Session API."""
    session = getattr(app.ctx, "session", None)
    if session is None:
        return

    if isinstance(result, Agenda):
        session.last_items = [item.value for item in result.items]
        session.current_selection = None
        return
    if isinstance(result, AgendaItem):
        session.last_items = [result.value]
        session.current_selection = result.value
        return
    if isinstance(result, (Task, Event)):
        session.current_selection = result


def _last_numbered_item(app: Any, token: str) -> Any:
    clean = token.strip()
    if not clean.isascii() or not clean.isdigit():
        return None

    session = getattr(app.ctx, "session", None)
    last_items = list(getattr(session, "last_items", ()) or ()) if session is not None else []
    if not last_items:
        return None

    index = int(clean)
    if index < 1 or index > len(last_items):
        raise ValidationError(
            f"List item {index} is out of range; choose 1-{len(last_items)} from the last displayed list."
        )
    selected = last_items[index - 1]
    session.current_selection = selected
    return selected


def _require_numbered_kind(
    selected: Any,
    expected: type,
    *,
    index: str,
    command: str,
) -> Any:
    if isinstance(selected, expected):
        return selected
    actual = (
        "event"
        if isinstance(selected, Event)
        else "task"
        if isinstance(selected, Task)
        else "item"
    )
    wanted = "task" if expected is Task else "event"
    raise ValidationError(
        f"List item {index} is an {actual}, not a {wanted}; '{command}' requires a {wanted}."
    )


def _resolve_numbered_reference(
    app: Any,
    command_name: str,
    args: tuple[Any, ...],
) -> tuple[Any, ...]:
    """Resolve visible list numbers to their exact Task/Event objects.

    The rule is deliberately narrow: only command positions that are object targets
    are resolved. Numeric titles still work when there is no active numbered list.
    Lists shown by ``today``/``tasks``/``events`` all populate the same Session
    ``last_items`` context, so every visible number means the same thing everywhere.
    """
    if command_name in {"start", "done", "edit", "edit-due"} and len(args) == 1:
        token = args[0]
        if not isinstance(token, str):
            return args
        selected = _last_numbered_item(app, token)
        if selected is None:
            return args
        return (
            _require_numbered_kind(
                selected,
                Task,
                index=token,
                command=command_name,
            ),
        )

    if command_name == "edit-event" and len(args) == 1:
        token = args[0]
        if not isinstance(token, str):
            return args
        selected = _last_numbered_item(app, token)
        if selected is None:
            return args
        return (
            _require_numbered_kind(
                selected,
                Event,
                index=token,
                command=command_name,
            ),
        )

    if command_name == "remove" and len(args) == 2:
        kind, token = args
        if not isinstance(kind, str) or not isinstance(token, str):
            return args
        kind_token = kind.strip().casefold()
        if kind_token in {"task", "todo", "t"}:
            expected: type | None = Task
        elif kind_token in {"event", "calendar", "e"}:
            expected = Event
        else:
            expected = None
        if expected is None:
            return args
        selected = _last_numbered_item(app, token)
        if selected is None:
            return args
        return (
            kind,
            _require_numbered_kind(
                selected,
                expected,
                index=token,
                command=command_name,
            ),
        )

    return args


def _render_result(app: Any, result: Any, *, paginate: bool = False) -> None:
    if result is None or result is EXIT_REPL:
        return
    _remember_result(app, result)
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

    if isinstance(result, Agenda):
        emit_agenda(app, result, paginate=paginate)
        return

    safe_lines = render_lines(result)
    if safe_lines is not None:
        emit_lines(app, safe_lines, paginate=paginate)
        return

    _ui_show(app, result)


def _execute(app: Any, parsed: ParsedCommand, *, paginate: bool = False) -> tuple[int, bool]:
    try:
        entry = app.commands.resolve(parsed.name)
    except NotFoundError:
        _error(app, _unsupported_command_message(app, parsed.name))
        return 2, False
    except CalDAVAssistantError as exc:
        _error(app, f"{type(exc).__name__}: {exc}")
        return 2, False

    if parsed.name.casefold() != entry.name.casefold():
        _ui_show(
            app,
            _t(app, "cli.command_resolution", "Command → {command}", command=entry.name),
        )

    try:
        args = _resolve_numbered_reference(app, entry.name, parsed.args)
        result = app.commands.run(entry.name, *args)
    except KeyboardInterrupt:
        _error(app, _t(app, "cli.cancelled", "Cancelled."))
        return 130, False
    except EOFError:
        return 0, True
    except NotFoundError as exc:
        if entry.name.casefold() == "help" and parsed.args:
            target = " ".join(parsed.args).strip()
            _error(app, _unsupported_command_message(app, target))
        else:
            _error(app, f"{type(exc).__name__}: {exc}")
        return 2, False
    except CalDAVAssistantError as exc:
        _error(app, f"{type(exc).__name__}: {exc}")
        return 2, False
    except (TypeError, ValueError) as exc:
        _error(app, _t(app, "cli.invalid_input", "Invalid input: {error}", error=exc))
        return 2, False
    except Exception as exc:
        _error(app, f"{type(exc).__name__}: {exc}")
        return 1, False

    if result is EXIT_REPL:
        return 0, True
    _render_result(app, result, paginate=paginate)
    return 0, False


def run_one_shot(app: Any, argv: Sequence[str]) -> int:
    if not argv:
        return 0
    name = str(argv[0]).strip()
    if not name:
        _error(app, _t(app, "cli.command_empty", "Command must not be empty."))
        return 2
    parsed = ParsedCommand(
        raw=" ".join(str(item) for item in argv),
        name=name,
        args=tuple(str(item) for item in argv[1:]),
    )
    code, _ = _execute(app, parsed, paginate=False)
    return code


def _emit_repl_started(app: Any) -> None:
    """Give enabled extensions one failure-isolated interactive-start hook."""
    extensions = getattr(app, "extensions", None)
    hooks = getattr(extensions, "hooks", None)
    emit = getattr(hooks, "emit", None)
    if callable(emit):
        emit("cli.repl.started", app.ctx)


def _guided_menu_command(app: Any) -> ParsedCommand | None:
    """Return the zero-learning Enter action only when this client has ``menu``."""
    try:
        app.commands.resolve("menu")
    except Exception:
        return None
    return ParsedCommand(raw="menu", name="menu", args=())


def run_repl(app: Any) -> int:
    _ui_show(app, _t(app, "cli.banner", "CalDAV Assistant"))
    _ui_show(
        app,
        _t(
            app,
            "cli.hint",
            "Press Enter for the guided menu. Commands are optional shortcuts. Ctrl-D or Ctrl-C exits.",
        ),
    )
    _emit_repl_started(app)
    last_code = 0
    while True:
        pending = getattr(app, "_pending_repl_line", None)
        if pending is not None:
            line = str(pending)
            delattr(app, "_pending_repl_line")
        else:
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
            _error(
                app,
                _t(app, "cli.invalid_input", "Invalid input: {error}", error=exc),
            )
            last_code = 2
            continue
        if parsed is None:
            parsed = _guided_menu_command(app)
            if parsed is None:
                continue
        code, should_exit = _execute(app, parsed, paginate=True)
        last_code = code
        if should_exit:
            return code


def run_cli(argv: Sequence[str] | None = None, *, app: Any = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if app is None:
        from ..bootstrap import build_cli_application

        app = build_cli_application()

    register_cli_builtin_commands(app.commands, app.ctx)
    register_crud_cli_commands(app.commands, app.ctx)
    register_navigation_cli_commands(app.commands, app.ctx)
    register_api_cli_command(app.commands)

    if "settings" not in app.commands.registry:
        register_settings_cli_command(app.commands, app.ctx)

    runtime = getattr(app, "runtime", None)
    if runtime is not None and "background" not in app.commands.registry:
        register_background_cli_command(app.commands, runtime, ui=app.ctx.ui)
    if runtime is not None and "undo" not in app.commands.registry:
        register_undo_cli_command(app.commands, runtime)

    local_background_command = bool(
        argv and str(argv[0]).strip().casefold() == "background"
    )

    if app.extensions is not None:
        register_extension_cli_commands(app.commands, app.extensions)
        if not local_background_command:
            app.extensions.load_enabled()

    if argv:
        return run_one_shot(app, argv)
    with completion_session(app):
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
