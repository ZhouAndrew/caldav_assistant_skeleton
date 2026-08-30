"""Render client-neutral presentation views to terminal text, JSON, or HTML."""
from __future__ import annotations

from html import escape
from typing import Any

from .models import MenuView


class TextRenderer:
    """Plain-text renderer used by the existing terminal client."""

    def render_lines(self, view: MenuView) -> list[str]:
        lines = [view.title]
        if view.query:
            lines.append(f"Search: {view.query} ({len(view.items)} match(es))")
        lines.extend(f"{item.key}. {item.label}" for item in view.items)
        if view.page_count > 1:
            lines.append(f"Page {view.page}/{view.page_count}")
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
                f"Search: {escape(view.query)} ({len(view.items)} match(es))"
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
