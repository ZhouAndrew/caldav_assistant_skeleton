"""Transport-neutral presentation data.

These objects describe what a client should present without deciding whether the
client is a terminal, browser, PWA, or another future frontend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MenuChoiceView:
    """One selectable menu item.

    ``value`` stays server-side/internal. Renderers expose the stable ``key`` and
    human label, never an arbitrary Python object representation.
    """

    key: str
    label: str
    value: Any = field(default=None, repr=False, compare=False)
    keywords: tuple[str, ...] = ()
    disabled: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "keywords": list(self.keywords),
            "disabled": self.disabled,
        }


@dataclass(frozen=True, slots=True)
class MenuView:
    """A complete menu page independent from its renderer."""

    title: str
    items: tuple[MenuChoiceView, ...]
    back_label: str = "Back"
    page: int = 1
    page_count: int = 1
    query: str = ""
    match_count: int | None = None
    multiple: bool = False
    searchable: bool = True
    default_key: str | None = None

    @property
    def kind(self) -> str:
        return "menu"

    @property
    def visible_match_count(self) -> int:
        return len(self.items) if self.match_count is None else int(self.match_count)

    def resolve(self, key: str) -> Any:
        """Resolve a client-submitted selection key to the internal value."""
        clean = str(key).strip()
        for item in self.items:
            if item.key == clean and not item.disabled:
                return item.value
        raise KeyError(clean)

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": self.kind,
            "title": self.title,
            "items": [item.to_payload() for item in self.items],
            "controls": {
                "back": {"key": "0", "label": self.back_label},
                "multiple": self.multiple,
                "searchable": self.searchable,
                "default_key": self.default_key,
            },
            "page": {
                "number": self.page,
                "count": self.page_count,
                "query": self.query,
                "match_count": self.visible_match_count,
            },
        }
