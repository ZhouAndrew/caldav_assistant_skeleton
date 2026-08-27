"""Non-interactive UI used by the authoritative background context."""
from __future__ import annotations

class HeadlessUI:
    def show(self, value): return value
    def _interactive(self, *args, **kwargs): raise RuntimeError("Interactive UI is unavailable in background service")
    ask_text = ask_date = ask_time = ask_datetime = choose = choose_many = choose_task = choose_event = confirm = _interactive

__all__ = ["HeadlessUI"]
