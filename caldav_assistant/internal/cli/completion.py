"""Interactive command-line completion for the CalDAV Assistant REPL.

The completion layer is deliberately separate from command execution.  It reads the
live CommandRegistry plus local metadata/catalogs and never calls CalDAV, IPC routes,
or Task/Event services merely because the user pressed Tab.

GNU readline is used on Unix-like systems.  On Windows the package dependency provides
the compatible ``readline`` module through pyreadline3.  If no readline-compatible
backend is available, the REPL continues normally without completion.
"""
from __future__ import annotations

import importlib
import shlex
import sys
from dataclasses import dataclass
from typing import Any, Iterable

from ...api import api_catalog


_API_VERBS = ("exists", "search", "list", "show")
_API_LAYERS = ("easy", "object", "full")
_EXTENSION_VERBS = (
    "guide",
    "new",
    "dev",
    "path",
    "official",
    "user",
    "info",
    "reset",
    "add",
    "load",
    "enable",
    "disable",
    "reload",
    "unload",
    "errors",
)
_EXTENSION_NAME_VERBS = {
    "info",
    "reset",
    "load",
    "enable",
    "disable",
    "reload",
    "unload",
    "errors",
}
_BACKGROUND_ACTIONS = (
    "status",
    "show",
    "start",
    "stop",
    "restart",
    "enable",
    "on",
    "disable",
    "off",
    "help",
    "?",
)


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    """Parsed completion state immediately before the cursor."""

    buffer: str
    cursor: int
    before: tuple[str, ...]
    current: str


def _tokenize_prefix(buffer: str, cursor: int | None = None) -> CompletionRequest:
    cursor = len(buffer) if cursor is None else max(0, min(int(cursor), len(buffer)))
    prefix = buffer[:cursor]
    trailing_space = bool(prefix and prefix[-1].isspace())
    try:
        tokens = tuple(shlex.split(prefix))
    except ValueError:
        # Completion should remain available while a quote is still unfinished.
        tokens = tuple(prefix.split())

    if trailing_space:
        before = tokens
        current = ""
    elif tokens:
        before = tokens[:-1]
        current = tokens[-1]
    else:
        before = ()
        current = ""
    return CompletionRequest(buffer=buffer, cursor=cursor, before=before, current=current)


def _matches(values: Iterable[str], prefix: str) -> tuple[str, ...]:
    needle = prefix.casefold()
    unique = {
        str(value)
        for value in values
        if isinstance(value, str)
        and value
        and str(value).casefold().startswith(needle)
    }
    return tuple(sorted(unique, key=lambda item: item.casefold()))


class CompletionEngine:
    """Pure completion logic backed by the live application registries."""

    def __init__(self, app: Any) -> None:
        self.app = app
        # Public API shape is immutable for the lifetime of one installed package, so
        # cache this moderately expensive introspection once per REPL session.
        self._api_paths = tuple(entry.path for entry in api_catalog())

    def _command_names(self) -> tuple[str, ...]:
        names = getattr(self.app.commands, "names", None)
        if callable(names):
            try:
                return tuple(names(include_aliases=True))
            except TypeError:
                return tuple(names())
        registry = getattr(self.app.commands, "registry", None)
        getter = getattr(registry, "names", None)
        return tuple(getter(include_aliases=True)) if callable(getter) else ()

    def _canonical_command(self, token: str) -> str | None:
        resolver = getattr(self.app.commands, "resolve", None)
        if callable(resolver):
            try:
                return str(resolver(token).name).casefold()
            except Exception:
                return None
        return token.casefold()

    def _extension_names(self) -> tuple[str, ...]:
        manager = getattr(self.app, "extensions", None)
        listing = getattr(manager, "list", None)
        if not callable(listing):
            return ()
        try:
            return tuple(
                str(record.name)
                for record in listing()
                if getattr(record, "name", None)
            )
        except Exception:
            # Completion is convenience only; extension discovery errors must not
            # interfere with normal command entry.
            return ()

    def _complete_api(self, args_before: tuple[str, ...], current: str) -> tuple[str, ...]:
        if not args_before:
            return _matches((*_API_VERBS, *self._api_paths), current)

        verb = args_before[0].casefold()
        if verb == "list" and len(args_before) == 1:
            return _matches(_API_LAYERS, current)
        if verb in {"exists", "show"} and len(args_before) == 1:
            return _matches(self._api_paths, current)
        if verb == "search":
            return ()
        return ()

    def _complete_extension(
        self,
        args_before: tuple[str, ...],
        current: str,
    ) -> tuple[str, ...]:
        if not args_before:
            return _matches(_EXTENSION_VERBS, current)
        verb = args_before[0].casefold()
        if verb in _EXTENSION_NAME_VERBS and len(args_before) == 1:
            return _matches(self._extension_names(), current)
        return ()

    def complete(self, buffer: str, cursor: int | None = None) -> tuple[str, ...]:
        request = _tokenize_prefix(buffer, cursor)
        if not request.before:
            return _matches(self._command_names(), request.current)

        command_token = request.before[0]
        canonical = self._canonical_command(command_token)
        if canonical is None:
            return ()
        args_before = request.before[1:]

        if canonical == "api":
            return self._complete_api(args_before, request.current)
        if canonical == "extension":
            return self._complete_extension(args_before, request.current)
        if canonical == "background" and not args_before:
            return _matches(_BACKGROUND_ACTIONS, request.current)
        if canonical == "help" and not args_before:
            return _matches(self._command_names(), request.current)
        return ()


class ReadlineCompletionSession:
    """Install and later restore one readline completer for a REPL session."""

    def __init__(
        self,
        app: Any,
        *,
        readline_module: Any = None,
        force: bool = False,
    ) -> None:
        self.app = app
        self.engine = CompletionEngine(app)
        self.readline = readline_module if readline_module is not None else self._load_readline()
        self.force = force
        self.active = False
        self._old_completer: Any = None
        self._old_delims: str | None = None
        self._matches: tuple[str, ...] = ()

    @staticmethod
    def _load_readline() -> Any:
        try:
            return importlib.import_module("readline")
        except (ImportError, ModuleNotFoundError):
            return None

    def _interactive_input(self) -> bool:
        if self.force:
            return True
        input_fn = getattr(getattr(self.app, "io", None), "_input_fn", None)
        if input_fn is not None:
            return False
        isatty = getattr(sys.stdin, "isatty", None)
        return bool(callable(isatty) and isatty())

    def _complete(self, text: str, state: int) -> str | None:
        if state == 0:
            try:
                buffer = self.readline.get_line_buffer()
                cursor = self.readline.get_endidx()
            except Exception:
                buffer, cursor = text, len(text)
            self._matches = self.engine.complete(buffer, cursor)
        return self._matches[state] if state < len(self._matches) else None

    def install(self) -> bool:
        if self.readline is None or not self._interactive_input():
            return False
        try:
            getter = getattr(self.readline, "get_completer", None)
            self._old_completer = getter() if callable(getter) else None
            get_delims = getattr(self.readline, "get_completer_delims", None)
            self._old_delims = get_delims() if callable(get_delims) else None
            self.readline.set_completer(self._complete)
            # Keep dots, dashes, slashes and question marks inside the token so
            # ``easy.complete``, ``edit-event`` and extension names complete intact.
            self.readline.set_completer_delims(" \t\n")
            try:
                self.readline.parse_and_bind("tab: complete")
            except Exception:
                # libedit-backed readline uses a different binding syntax.
                self.readline.parse_and_bind("bind ^I rl_complete")
            self.active = True
            return True
        except Exception:
            self.restore()
            return False

    def restore(self) -> None:
        if self.readline is None:
            return
        try:
            self.readline.set_completer(self._old_completer)
            if self._old_delims is not None:
                self.readline.set_completer_delims(self._old_delims)
        except Exception:
            pass
        self.active = False

    def __enter__(self) -> "ReadlineCompletionSession":
        self.install()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.restore()


def completion_session(app: Any) -> ReadlineCompletionSession:
    return ReadlineCompletionSession(app)


__all__ = [
    "CompletionEngine",
    "CompletionRequest",
    "ReadlineCompletionSession",
    "completion_session",
]
