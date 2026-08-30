"""Reusable Menu / Choice bricks with client-neutral presentation output.

MODULE CONTRACT
- Imports/calls: console-like IO and presentation models/renderers only.
- Provides: Choice, Menu.choose(), Menu.choose_many(), Menu.presentation().
- Must not: know Task/Event business rules, CalDAV, SQLite, commands, or mutate data.

Frozen interaction behavior:
- numeric selection
- 0 / back
- q / cancel
- ? / help
- optional paging, default, multiple selection and search

A menu is described once as ``MenuView``. The terminal client renders that view as
text; browser clients can render the same view as JSON or HTML.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..presentation import MenuChoiceView, MenuView, TextRenderer, render_view


@dataclass(frozen=True)
class Choice:
    """One display label mapped to an arbitrary value."""

    label: str
    value: Any
    keywords: tuple[str, ...] = ()


class Menu:
    BACK_TOKENS = frozenset({"0", "back", "b"})
    CANCEL_TOKENS = frozenset({"q", "quit", "cancel", "c"})
    HELP_TOKENS = frozenset({"?", "help", "h"})
    NEXT_TOKENS = frozenset({"n", "next", ">"})
    PREV_TOKENS = frozenset({"p", "prev", "previous", "<"})

    def __init__(self, io: Any, *, page_size: int = 10, locale: Any = None) -> None:
        self.io = io
        self.page_size = max(1, int(page_size))
        self.locale = locale

    def _t(self, key: str, default: str) -> str:
        translate = getattr(self.locale, "t", None)
        if callable(translate):
            return translate(key, default=default)
        return default

    # IO is intentionally duck-typed so Prompt/Menu does not own the CLI adapter.
    def _read(self, prompt: str = "> ") -> str:
        for name in ("read", "input", "ask"):
            fn = getattr(self.io, name, None)
            if callable(fn):
                try:
                    value = fn(prompt)
                except TypeError:
                    self._write(prompt, end="")
                    value = fn()
                return "" if value is None else str(value)
        return input(prompt)

    def _write(self, text: Any = "", *, end: str = "\n") -> None:
        value = str(text)
        for name in ("write", "print", "output"):
            fn = getattr(self.io, name, None)
            if callable(fn):
                try:
                    fn(value, end=end)
                except TypeError:
                    fn(value if end == "\n" else value + end)
                return
        print(value, end=end)

    @staticmethod
    def _label(value: Any) -> str:
        for attr in ("summary", "title", "name", "label"):
            candidate = getattr(value, attr, None)
            if candidate not in (None, "") and not callable(candidate):
                return str(candidate)
        return str(value)

    @classmethod
    def _choices(
        cls,
        items: Iterable[Any] | Mapping[Any, Any],
        *,
        item_label: Callable[[Any], str] | None = None,
    ) -> list[Choice]:
        if isinstance(items, Mapping):
            raw_items = [Choice(str(label), value) for label, value in items.items()]
        else:
            raw_items = []
            for item in list(items or ()):
                if isinstance(item, Choice):
                    raw_items.append(item)
                elif isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str):
                    raw_items.append(Choice(item[0], item[1]))
                else:
                    label = item_label(item) if item_label else cls._label(item)
                    raw_items.append(Choice(str(label), item))
        return raw_items

    @staticmethod
    def _search(choices: Sequence[Choice], query: str) -> list[Choice]:
        needle = query.strip().casefold()
        if not needle:
            return list(choices)
        return [
            choice
            for choice in choices
            if needle in choice.label.casefold()
            or any(needle in keyword.casefold() for keyword in choice.keywords)
        ]

    @staticmethod
    def _exact(choices: Sequence[Choice], text: str) -> Choice | None:
        needle = text.strip().casefold()
        if not needle:
            return None
        matches = [choice for choice in choices if choice.label.strip().casefold() == needle]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _parse_many(text: str, max_index: int) -> list[int] | None:
        values: list[int] = []
        try:
            for token in text.replace(";", ",").split(","):
                token = token.strip()
                if not token:
                    continue
                if "-" in token:
                    left, right = token.split("-", 1)
                    start, end = int(left), int(right)
                    if start > end:
                        start, end = end, start
                    values.extend(range(start, end + 1))
                else:
                    values.append(int(token))
        except ValueError:
            return None
        if not values or any(index < 1 or index > max_index for index in values):
            return None
        return list(dict.fromkeys(values))

    def _show_help(self, *, multiple: bool, searchable: bool, paged: bool, extra: str | None) -> None:
        lines = [
            "number or exact label: choose",
            f"0/back: {self._t('menu.back', 'Back')}",
            f"q/cancel: {self._t('menu.cancel', 'Cancel')}",
            f"?/help: {self._t('menu.help', 'Help')}",
        ]
        if multiple:
            lines.append("1,3,5-7: choose multiple")
        if searchable:
            lines.append("/text or search text: filter")
        if paged:
            lines.append("n/next, p/prev: change page")
        if extra:
            lines.append(str(extra))
        self._write(" | ".join(lines))

    @staticmethod
    def _resolve_default(default: Any, choices: Sequence[Choice]) -> int | None:
        if default is None:
            return None
        if isinstance(default, int) and 1 <= default <= len(choices):
            return default
        for index, choice in enumerate(choices, 1):
            try:
                if choice.value is default or choice.value == default or choice.label == default:
                    return index
            except Exception:
                if choice.value is default or choice.label == default:
                    return index
        return None

    def _presentation_from_filtered(
        self,
        title: str,
        filtered: Sequence[Choice],
        *,
        page: int,
        size: int,
        query: str,
        multiple: bool,
        searchable: bool,
        default: Any,
    ) -> MenuView:
        page_count = max(1, (len(filtered) + size - 1) // size)
        page = min(max(0, int(page)), page_count - 1)
        start = page * size
        current = filtered[start : start + size]
        items = tuple(
            MenuChoiceView(
                key=str(offset),
                label=choice.label,
                value=choice.value,
                keywords=choice.keywords,
            )
            for offset, choice in enumerate(current, start + 1)
        )
        default_index = self._resolve_default(default, filtered)
        return MenuView(
            title=str(title),
            items=items,
            back_label=self._t("menu.back", "Back"),
            page=page + 1,
            page_count=page_count,
            query=query,
            match_count=len(filtered),
            multiple=multiple,
            searchable=searchable,
            default_key=str(default_index) if default_index is not None else None,
        )

    def presentation(
        self,
        title: str,
        items: Iterable[Any] | Mapping[Any, Any],
        *,
        page: int = 1,
        page_size: int | None = None,
        query: str = "",
        multiple: bool = False,
        searchable: bool = True,
        default: Any = None,
        item_label: Callable[[Any], str] | None = None,
    ) -> MenuView:
        """Build the same menu page for terminal, JSON, HTML, or future clients."""
        choices = self._choices(items, item_label=item_label)
        filtered = self._search(choices, query) if query else list(choices)
        size = max(1, int(page_size or self.page_size))
        return self._presentation_from_filtered(
            title,
            filtered,
            page=max(0, int(page) - 1),
            size=size,
            query=query,
            multiple=multiple,
            searchable=searchable,
            default=default,
        )

    @staticmethod
    def render_presentation(view: MenuView, format: str = "text") -> Any:
        """Render an already-built view without rebuilding menu/business logic."""
        return render_view(view, format)

    def _show_presentation(self, view: MenuView) -> None:
        for line in TextRenderer().render_lines(view):
            self._write(line)

    def choose(
        self,
        title: str,
        items: Iterable[Any] | Mapping[Any, Any],
        *,
        multiple: bool = False,
        default: Any = None,
        page_size: int | None = None,
        searchable: bool = True,
        help_text: str | None = None,
        item_label: Callable[[Any], str] | None = None,
        empty_message: str = "No choices available.",
    ) -> Any:
        all_choices = self._choices(items, item_label=item_label)
        if not all_choices:
            self._write(empty_message)
            return [] if multiple else None

        size = max(1, int(page_size or self.page_size))
        filtered = list(all_choices)
        page = 0
        query = ""

        while True:
            page_count = max(1, (len(filtered) + size - 1) // size)
            page = min(page, page_count - 1)
            view = self._presentation_from_filtered(
                title,
                filtered,
                page=page,
                size=size,
                query=query,
                multiple=multiple,
                searchable=searchable,
                default=default,
            )
            self._show_presentation(view)

            default_index = self._resolve_default(default, filtered)
            prompt = f"> [{default_index}] " if default_index else "> "
            raw = self._read(prompt).strip()
            token = raw.casefold()

            if not raw and default_index:
                choice = filtered[default_index - 1]
                return [choice.value] if multiple else choice.value
            if token in self.BACK_TOKENS or token in self.CANCEL_TOKENS:
                return [] if multiple else None
            if token in self.HELP_TOKENS:
                self._show_help(
                    multiple=multiple,
                    searchable=searchable,
                    paged=page_count > 1,
                    extra=help_text,
                )
                continue
            if token in self.NEXT_TOKENS and page_count > 1:
                page = min(page + 1, page_count - 1)
                continue
            if token in self.PREV_TOKENS and page_count > 1:
                page = max(0, page - 1)
                continue

            exact = self._exact(filtered, raw)
            if exact is not None and not multiple:
                return exact.value

            search_query = None
            if searchable and raw.startswith("/"):
                search_query = raw[1:].strip()
            elif searchable and token.startswith("search "):
                search_query = raw.split(None, 1)[1].strip()
            elif searchable and token.startswith("s "):
                search_query = raw.split(None, 1)[1].strip()
            if search_query is not None:
                query = search_query
                filtered = self._search(all_choices, query)
                page = 0
                if not filtered:
                    self._write("No matches. Use / to clear the search or try another term.")
                    filtered = list(all_choices)
                    query = ""
                continue

            if multiple:
                indexes = self._parse_many(raw, len(filtered))
                if indexes is not None:
                    return [filtered[index - 1].value for index in indexes]
            else:
                try:
                    index = int(raw)
                except ValueError:
                    index = -1
                if 1 <= index <= len(filtered):
                    return filtered[index - 1].value

            self._write("Invalid choice. Enter a number or exact label, 0/back, q/cancel, or ?/help.")

    def choose_many(self, title: str, items: Iterable[Any], **options: Any) -> list[Any]:
        return list(self.choose(title, items, multiple=True, **options) or [])
