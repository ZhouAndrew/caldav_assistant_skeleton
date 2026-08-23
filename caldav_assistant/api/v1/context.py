from __future__ import annotations
from dataclasses import dataclass
from typing import Any
@dataclass
class AssistantContext:
    tasks: Any
    events: Any
    agenda: Any
    reminders: Any
    notifications: Any
    wordpress: Any
    ui: Any
    time: Any
    commands: Any
    activity: Any
    settings: Any
    session: Any
