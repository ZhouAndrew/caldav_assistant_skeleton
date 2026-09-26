"""Client-neutral presentation models and renderers.

Internal only. Core/business services must not depend on a concrete terminal or web UI.
"""

from .models import (
    DatePickerView,
    MenuChoiceView,
    MenuView,
    ScrollableListView,
    TaskPickerView,
)
from .renderers import HtmlRenderer, JsonRenderer, TextRenderer, render_view

__all__ = [
    "MenuChoiceView",
    "MenuView",
    "DatePickerView",
    "ScrollableListView",
    "TaskPickerView",
    "TextRenderer",
    "JsonRenderer",
    "HtmlRenderer",
    "render_view",
]
