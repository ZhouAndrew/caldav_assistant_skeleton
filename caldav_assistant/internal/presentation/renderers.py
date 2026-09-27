"""Render client-neutral presentation views to terminal text, JSON, or HTML."""
from __future__ import annotations

from html import escape
from typing import Any
import unicodedata

from .models import DatePickerView, MenuView, ScrollableListView, TaskPickerView


def _display_width(text: str) -> int:
    """Approximate terminal cell width without adding a wcwidth dependency."""
    width = 0
    for char in str(text):
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


class TextRenderer:
    """Dependency-free text renderer for all client-neutral presentation views."""

    def __init__(self, *, max_width: int | None = None, column_gap: int = 3) -> None:
        self.max_width = int(max_width) if max_width is not None else None
        self.column_gap = max(1, int(column_gap))

    @staticmethod
    def _pad_display(text: str, width: int) -> str:
        return text + (" " * max(0, int(width) - _display_width(text)))

    def _grid_for_columns(
        self,
        cells: list[str],
        columns: int,
    ) -> tuple[list[int], int, int]:
        rows = (len(cells) + columns - 1) // columns
        actual_columns = (len(cells) + rows - 1) // rows
        widths = [0] * actual_columns
        for index, cell in enumerate(cells):
            column = index // rows
            widths[column] = max(widths[column], _display_width(cell))
        total = sum(widths) + self.column_gap * (actual_columns - 1)
        return widths, total, rows

    def _render_choice_lines(self, view: MenuView) -> list[str]:
        cells = [f"{item.key}. {item.label}" for item in view.items]
        width = self.max_width
        if len(cells) < 4 or width is None:
            return cells

        max_columns = min(len(cells), 8)
        chosen_columns = 1
        chosen_rows = len(cells)
        chosen_widths = [_display_width(cell) for cell in cells[:1]]
        for columns in range(max_columns, 1, -1):
            widths, total, rows = self._grid_for_columns(cells, columns)
            if total <= width:
                chosen_columns = len(widths)
                chosen_rows = rows
                chosen_widths = widths
                break

        if chosen_columns == 1:
            return cells

        gap = " " * self.column_gap
        lines: list[str] = []
        for row in range(chosen_rows):
            rendered: list[tuple[int, str]] = []
            for column in range(chosen_columns):
                index = column * chosen_rows + row
                if index < len(cells):
                    rendered.append((column, cells[index]))

            aligned: list[str] = []
            for offset, (column, cell) in enumerate(rendered):
                if offset == len(rendered) - 1:
                    aligned.append(cell)
                else:
                    aligned.append(self._pad_display(cell, chosen_widths[column]))
            lines.append(gap.join(aligned))
        return lines

    def _menu_lines(self, view: MenuView) -> list[str]:
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

    @staticmethod
    def _date_picker_lines(view: DatePickerView) -> list[str]:
        marked = set(view.marked_dates)
        lines = [view.title, f"< {view.month_label} >", "Mon Tue Wed Thu Fri Sat Sun"]
        for week in view.weeks:
            cells: list[str] = []
            for day in week:
                if day.month != view.selected.month:
                    cell = "  "
                elif day == view.selected:
                    cell = f"[{day.day:02d}]"
                elif day in marked:
                    cell = f"{day.day:02d}•"
                elif day == view.today:
                    cell = f"*{day.day:02d}"
                else:
                    cell = f"{day.day:02d}"
                cells.append(cell)
            lines.append(" ".join(cells).rstrip())
        lines.append(f"Selected: {view.selected.isoformat()}")
        return lines

    @staticmethod
    def _scrollable_lines(view: ScrollableListView) -> list[str]:
        lines = [view.title]
        for visible_index, label in enumerate(view.visible_labels):
            absolute_index = view.offset + visible_index
            pointer = ">" if absolute_index == view.selected_index else " "
            lines.append(f"{pointer} {absolute_index + 1}. {label}")
        if not view.visible_labels:
            lines.append("(No choices)")
        if len(view.labels) > view.page_size:
            first = view.offset + 1
            last = min(len(view.labels), view.offset + view.page_size)
            lines.append(f"showing {first}-{last} of {len(view.labels)}")
        return lines

    def render_lines(self, view: Any) -> list[str]:
        if isinstance(view, MenuView):
            return self._menu_lines(view)
        if isinstance(view, DatePickerView):
            return self._date_picker_lines(view)
        if isinstance(view, ScrollableListView):
            return self._scrollable_lines(view)
        if isinstance(view, TaskPickerView):
            lines = [view.title, ""]
            calendar = self._date_picker_lines(view.calendar)
            if calendar and calendar[0] == view.calendar.title:
                calendar = calendar[1:]
            lines.extend(calendar)
            lines.append("")
            lines.extend(self._scrollable_lines(view.tasks))
            if view.footer:
                lines.extend(["", view.footer])
            return lines
        raise TypeError(f"Unsupported presentation view: {type(view).__name__}")

    def render(self, view: Any) -> str:
        return "\n".join(self.render_lines(view))


class JsonRenderer:
    """Structured payload renderer for HTTP/WebSocket clients."""

    def render(self, view: Any) -> dict[str, Any]:
        serializer = getattr(view, "to_payload", None)
        if not callable(serializer):
            raise TypeError(f"View is not serializable: {type(view).__name__}")
        return serializer()


class HtmlRenderer:
    """Dependency-free HTML renderer for browser clients or static export."""

    @staticmethod
    def _menu(view: MenuView) -> str:
        parts = [
            '<section class="caldav-assistant-menu" data-view="menu">',
            f"<h2>{escape(view.title)}</h2>",
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

    @staticmethod
    def _date_picker(view: DatePickerView) -> str:
        marked = set(view.marked_dates)
        parts = [
            '<section class="caldav-assistant-date-picker" data-view="date_picker">',
            f"<h2>{escape(view.title)}</h2>",
            '<div class="caldav-assistant-calendar-header">',
            f"<strong>{escape(view.month_label)}</strong>",
            "</div>",
            '<table class="caldav-assistant-calendar"><thead><tr>',
        ]
        for name in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            parts.append(f"<th>{name}</th>")
        parts.append("</tr></thead><tbody>")
        for week in view.weeks:
            parts.append("<tr>")
            for day in week:
                classes = ["day"]
                if day.month != view.selected.month:
                    classes.append("outside-month")
                if day == view.today:
                    classes.append("today")
                if day == view.selected:
                    classes.append("selected")
                if day in marked:
                    classes.append("marked")
                class_attr = " ".join(classes)
                parts.append(
                    f'<td><button type="button" class="{class_attr}" '
                    f'data-date="{day.isoformat()}">{day.day}</button></td>'
                )
            parts.append("</tr>")
        parts.extend(
            [
                "</tbody></table>",
                '<p class="caldav-assistant-selected-date">'
                f"Selected: {view.selected.isoformat()}</p>",
                "</section>",
            ]
        )
        return "".join(parts)

    @staticmethod
    def _scrollable(view: ScrollableListView) -> str:
        parts = [
            '<section class="caldav-assistant-scrollable-list" '
            'data-view="scrollable_list">',
            f"<h2>{escape(view.title)}</h2>",
            '<div class="caldav-assistant-scrollable-items">',
        ]
        for visible_index, label in enumerate(view.visible_labels):
            absolute_index = view.offset + visible_index
            selected = (
                ' aria-current="true" class="selected"'
                if absolute_index == view.selected_index
                else ""
            )
            parts.append(
                f'<button type="button" data-index="{absolute_index}"{selected}>'
                f'<span class="key">{absolute_index + 1}</span>. '
                f'<span class="label">{escape(label)}</span>'
                "</button>"
            )
        if not view.visible_labels:
            parts.append('<p class="empty">No choices</p>')
        parts.extend(["</div>", "</section>"])
        return "".join(parts)

    def render(self, view: Any) -> str:
        if isinstance(view, MenuView):
            return self._menu(view)
        if isinstance(view, DatePickerView):
            return self._date_picker(view)
        if isinstance(view, ScrollableListView):
            return self._scrollable(view)
        if isinstance(view, TaskPickerView):
            return "".join(
                [
                    '<section class="caldav-assistant-task-picker" data-view="task_picker">',
                    f"<h1>{escape(view.title)}</h1>",
                    self._date_picker(view.calendar),
                    self._scrollable(view.tasks),
                    (
                        f'<footer>{escape(view.footer)}</footer>'
                        if view.footer
                        else ""
                    ),
                    "</section>",
                ]
            )
        raise TypeError(f"Unsupported presentation view: {type(view).__name__}")


def render_view(view: Any, format: str = "text") -> Any:
    """Render one client-neutral view without exposing client choice to business code."""
    normalized = str(format).strip().casefold()
    if normalized in {"text", "txt", "terminal", "cli"}:
        return TextRenderer().render(view)
    if normalized in {"json", "structured"}:
        return JsonRenderer().render(view)
    if normalized in {"html", "web"}:
        return HtmlRenderer().render(view)
    raise ValueError(f"Unsupported presentation format: {format}")
