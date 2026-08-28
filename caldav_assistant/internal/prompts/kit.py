"""Unified PromptKit for all interactive CLI input.

MODULE CONTRACT
- Imports/calls: injected IO, Menu, TemporalService, and read-only Task/Event APIs.
- Provides: ask_text/date/time/datetime/duration/yes_no, choose variants,
  choose_task/event, confirm/confirm_danger and show.
- Must not: perform Task/Event mutations, access CalDAV/XML/SQLite, or duplicate
  TemporalParser business.

All bad user input is recoverable and visible; parser exceptions are shown and the
prompt is repeated. q/cancel/back may leave a prompt without crashing the REPL.
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Callable

from .menu import Menu


class PromptKit:
    CANCEL_TOKENS = frozenset({"q", "quit", "cancel", "c", "back", "b", "0"})

    def __init__(
        self,
        io: Any,
        menu: Menu,
        temporal: Any,
        tasks: Any = None,
        events: Any = None,
        *,
        locale: Any = None,
    ) -> None:
        self.io = io
        self.menu = menu
        self.temporal = temporal
        self.tasks = tasks
        self.events = events
        self.locale = locale

    def t(self, key: str, default: str | None = None, **values: Any) -> str:
        translate = getattr(self.locale, "t", None)
        if callable(translate):
            return translate(key, default=default, **values)
        text = key if default is None else default
        try:
            return str(text).format(**values)
        except Exception:
            return str(text)

    def set_locale(self, code: str, *, persist: bool = True) -> str:
        setter = getattr(self.locale, "set_locale", None)
        if not callable(setter):
            raise RuntimeError("LocaleService is unavailable")
        return setter(code, persist=persist)

    def _read(self, prompt: str) -> str:
        return self.menu._read(prompt)

    def _write(self, value: Any = "") -> None:
        self.menu._write(value)

    @classmethod
    def _cancelled(cls, text: str) -> bool:
        return text.strip().casefold() in cls.CANCEL_TOKENS

    def show(self, value: Any) -> None:
        if isinstance(value, (list, tuple)):
            for item in value:
                self._write(self._display_label(item))
        else:
            self._write(value)

    def ask_text(
        self,
        prompt: str = "Text?",
        *,
        default: str | None = None,
        allow_empty: bool = False,
        validator: Callable[[str], Any] | None = None,
        help_text: str | None = None,
        strip: bool = True,
    ) -> str | None:
        while True:
            suffix = f" [{default}]" if default is not None else ""
            raw = self._read(f"{prompt}{suffix}: ")
            text = raw.strip() if strip else raw
            if self._cancelled(text):
                return None
            if not text and default is not None:
                text = default
            if not text and not allow_empty:
                self._write("Input cannot be empty. Enter q/cancel to leave.")
                continue
            if text in {"?", "help"} and help_text:
                self._write(help_text)
                continue
            if validator is not None:
                try:
                    result = validator(text)
                except Exception as exc:
                    self._write(f"Invalid input: {exc}")
                    continue
                if result is False:
                    self._write("Invalid input. Please try again.")
                    continue
            return text

    def _ask_parsed(self, method: str, prompt: str, *, bias: str | None = None, default: Any = None) -> Any:
        parser = getattr(self.temporal, method)
        while True:
            raw = self.ask_text(prompt, default=None if default is None else str(default))
            if raw is None:
                return None
            try:
                if bias is None:
                    return parser(raw)
                return parser(raw, bias=bias)
            except Exception as exc:
                self._write(f"Could not understand {raw!r}: {exc}")

    def ask_date(self, prompt: str = "Date?", *, bias: str = "any", default: Any = None) -> Any:
        return self._ask_parsed("parse_date", prompt, bias=bias, default=default)

    def ask_datetime(self, prompt: str = "Date/time?", *, bias: str = "any", default: Any = None) -> Any:
        return self._ask_parsed("parse_datetime", prompt, bias=bias, default=default)

    def ask_time(self, prompt: str = "Time?", *, default: Any = None) -> Any:
        if callable(getattr(self.temporal, "parse_time", None)):
            return self._ask_parsed("parse_time", prompt, default=default)
        value = self._ask_parsed("parse_datetime", prompt, default=default)
        return value.time() if value is not None and hasattr(value, "time") else value

    @staticmethod
    def _parse_duration_text(text: str) -> timedelta:
        raw = text.strip().casefold().replace(" ", "")
        if raw.isdigit():
            return timedelta(minutes=int(raw))
        if re.fullmatch(r"\d{1,3}:\d{1,2}", raw):
            hours, minutes = map(int, raw.split(":"))
            if minutes >= 60:
                raise ValueError("minutes after ':' must be below 60")
            return timedelta(hours=hours, minutes=minutes)
        matches = re.findall(r"(\d+(?:\.\d+)?)(d|h|m|s)", raw)
        if matches and "".join(value + unit for value, unit in matches) == raw:
            seconds = 0.0
            scale = {"d": 86400, "h": 3600, "m": 60, "s": 1}
            for value, unit in matches:
                seconds += float(value) * scale[unit]
            return timedelta(seconds=seconds)
        raise ValueError("use e.g. 90m, 1h30m, 2:15, or plain minutes")

    def ask_duration(self, prompt: str = "Duration?", *, default: Any = None) -> Any:
        parser = getattr(self.temporal, "parse_duration", None)
        while True:
            raw = self.ask_text(prompt, default=None if default is None else str(default))
            if raw is None:
                return None
            try:
                return parser(raw) if callable(parser) else self._parse_duration_text(raw)
            except Exception as exc:
                self._write(f"Invalid duration: {exc}")

    def ask_yes_no(self, prompt: str, *, default: bool | None = None) -> bool | None:
        suffix = " [Y/n]" if default is True else " [y/N]" if default is False else " [y/n]"
        while True:
            raw = self._read(f"{prompt}{suffix}: ").strip().casefold()
            if not raw and default is not None:
                return default
            if raw in {"y", "yes", "true", "1"}:
                return True
            if raw in {"n", "no", "false"}:
                return False
            if raw in self.CANCEL_TOKENS:
                return None
            if raw in {"?", "help"}:
                self._write("y/yes = yes | n/no = no | q/cancel/back = leave")
                continue
            self._write("Please answer y/yes or n/no.")

    def confirm(self, text: str, **options: Any) -> bool:
        return self.ask_yes_no(text, **options) is True

    def confirm_danger(
        self,
        text: str,
        *,
        confirmation: str = "YES",
        case_sensitive: bool = False,
    ) -> bool:
        """Stronger confirmation brick for destructive/high-risk operations."""
        self._write(text)
        raw = self._read(f"Type {confirmation!r} to confirm (q/cancel to abort): ").strip()
        if self._cancelled(raw):
            return False
        if case_sensitive:
            return raw == confirmation
        return raw.casefold() == confirmation.casefold()

    def choose(self, title: str, items: Any, **options: Any) -> Any:
        return self.menu.choose(title, items, **options)

    def choose_many(self, title: str, items: Any, **options: Any) -> list[Any]:
        return self.menu.choose_many(title, items, **options)

    @staticmethod
    def _display_label(item: Any) -> str:
        summary = getattr(item, "summary", None) or getattr(item, "title", None) or str(item)
        when = getattr(item, "due", None) or getattr(item, "start", None)
        return f"{summary} — {when}" if when is not None else str(summary)

    def choose_task(self, title: str | None = None, **filters: Any) -> Any:
        if self.tasks is None:
            self._write("Task service is unavailable.")
            return None
        items = list(self.tasks.list(**filters) or ())
        title = title or self.t("prompt.choose_task", "Choose task")
        return self.menu.choose(title, items, item_label=self._display_label)

    def choose_event(self, title: str | None = None, **filters: Any) -> Any:
        if self.events is None:
            self._write("Event service is unavailable.")
            return None
        items = list(self.events.list(**filters) or ())
        title = title or self.t("prompt.choose_event", "Choose event")
        return self.menu.choose(title, items, item_label=self._display_label)

    # CALDAV_ASSISTANT_PRODUCTION_INTEGRATION_V1
    def ask_secret(self, prompt: str = "Password") -> str | None:
        """Read a secret without echoing it; secret input stays inside PromptKit."""
        reader = getattr(getattr(self, "io", None), "ask_secret", None)
        if callable(reader):
            return reader(prompt)

        import getpass
        label = str(prompt)
        if label and not label.endswith((" ", ": ")):
            label += ": "
        value = getpass.getpass(label)
        if value.strip().casefold() in {"q", "cancel"}:
            return None
        return value
