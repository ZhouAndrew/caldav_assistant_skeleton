from .assistant_engine import AssistantReminderEngine
from .engine import NotificationRequest
from .follow_up import TaskFollowUpPolicy
from .service import ReminderService

# Production/default composition keeps the long-standing package import stable:
# ``from caldav_assistant.internal.reminders import ReminderEngine``.
ReminderEngine = AssistantReminderEngine

__all__ = [
    "NotificationRequest",
    "ReminderEngine",
    "AssistantReminderEngine",
    "TaskFollowUpPolicy",
    "ReminderService",
]
