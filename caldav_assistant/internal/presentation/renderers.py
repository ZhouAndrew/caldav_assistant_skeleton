"""Render client-neutral presentation views to terminal text, JSON, or HTML."""
from __future__ import annotations

from html import escape
from typing import Any
import unicodedata

from .models import MenuView


def _display_width(text: str) -> int:
    """Approximate terminal cell width without adding a wcwidth dependency."""
    width = 0
    for char in str(text):
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


class TextRenderer:
    """Plain-text renderer used by terminal-like clients.

    max_width is optional. When supplied, short menu choices are packed
    left-to-right onto the same line while preserving numeric order. Long choices,
    narrow terminals, redirected output, and clients that do not provide a width
    naturally keep the historical one-item-per-line rendering.
    """

    def __init__(self, *, max_width: int | None = None, column_gap: int = 3) -> None:
        self.max_width = int(max_width) if max_width is not None else None
        self.column_gap = max(1, int(column_gap))

    @staticmethod
    def _pad_display(text: str, width: int) -> str:
        """Pad by terminal-cell width rather than Python character count."""
        return text + (" " * max(0, int(width) - _display_width(text)))

    def _grid_for_columns(self, cells: list[str], columns: int) -> tuple[list[int], int]:
        """Return per-column widths and total rendered width for row-major layout."""
        widths = [0] * columns
        for index, cell in enumerate(cells):
            column = index % columns
            widths[column] = max(widths[column], _display_width(cell))
        total = sum(widths) + self.column_gap * (columns - 1)
        return widths, total

    def _render_choice_lines(self, view: MenuView) -> list[str]:
        cells = [f"{item.key}. {item.label}" for item in view.items]
        width = self.max_width
        if len(cells) < 4 or width is None or width < 50:
            return cells

        # Pick the widest *aligned* grid that fits. This deliberately differs from
        # greedy line packing: every row uses the same column starts, so mixed short
        # and long labels remain visually scannable. Long menus may therefore use
        # fewer columns than a greedy packer would.
        max_columns = min(len(cells), 8)
        chosen_columns = 1
        chosen_widths = [_display_width(cell) for cell in cells[:1]]
        for columns in range(max_columns, 1, -1):
            widths, total = self._grid_for_columns(cells, columns)
            if total <= width:
                chosen_columns = columns
                chosen_widths = widths
                break

        if chosen_columns == 1:
            return cells

        gap = " " * self.column_gap
        lines: list[str] = []
        for row_start in range(0, len(cells), chosen_columns):
            row = cells[row_start : row_start + chosen_columns]
            rendered: list[str] = []
            for column, cell in enumerate(row):
                is_last = column == len(row) - 1
                if is_last:
                    rendered.append(cell)
                else:
                    rendered.append(self._pad_display(cell, chosen_widths[column]))
            lines.append(gap.join(rendered))
        return lines

    def render_lines(self, view: MenuView) -> list[str]:
        lines = [view.title]
        if view.query:
            lines.append(
                f"Search: {view.query} ({view.visible_match_count} match(es))"
            )
        lines.extend(self._render_choice_lines(view))
        if view.page_count > 1:
            lines.append(f"Page {view.page}/{view.page_count}")
            paging = []
            if view.page > 1:
                paging.append("p/prev. Previous page")
            if view.page < view.page_count:
                paging.append("n/next. Next page")
            lines.append(" | ".join(paging))
        lines.append(f"0. {view.back_label}")
        return lines

    def render(self, view: MenuView) -> str:
        return "\n".join(self.render_lines(view))


class JsonRenderer:
    """Structured payload renderer for HTTP/WebSocket clients."""

    def render(self, view: MenuView) -> dict[str, Any]:
        return view.to_payload()


class HtmlRenderer:
    """Small dependency-free HTML renderer for browser clients or static export."""

    def render(self, view: MenuView) -> str:
        title = escape(view.title)
        parts = [
            '<section class="caldav-assistant-menu" data-view="menu">',
            f"<h2>{title}</h2>",
        ]
        if view.query:
            parts.append(
                '<p class="caldav-assistant-menu-search">'
                f"Search: {escape(view.query)} ({view.visible_match_count} match(es))"
                "</p>"
            )
        parts.append('<div class="caldav-assistant-menu-items">')
        for item in view.items:
            disabled = " disabled" if item.disabled else ""
            parts.append(
                '<button type="button" class="caldav-assistant-menu-item" '
                f'data-choice-key="{escape(item.key, quote=True)}"{disabled}>'
                f'<span class="key">{escape(item.key)}</span>. '
                f'<span class="label">{escape(item.label)}</span>'
                "</button>"
            )
        parts.append("</div>")
        if view.page_count > 1:
            parts.append(
                '<p class="caldav-assistant-menu-page">'
                f"Page {view.page}/{view.page_count}"
                "</p>"
            )
        parts.append(
            '<button type="button" class="caldav-assistant-menu-back" '
            'data-choice-key="0">'
            f"0. {escape(view.back_label)}"
            "</button>"
        )
        parts.append("</section>")
        return "".join(parts)


def render_view(view: MenuView, format: str = "text") -> Any:
    """Render one view without exposing renderer selection to business code."""
    normalized = str(format).strip().casefold()
    if normalized in {"text", "txt", "terminal", "cli"}:
        return TextRenderer().render(view)
    if normalized in {"json", "structured"}:
        return JsonRenderer().render(view)
    if normalized in {"html", "web"}:
        return HtmlRenderer().render(view)
    raise ValueError(f"Unsupported presentation format: {format}")
