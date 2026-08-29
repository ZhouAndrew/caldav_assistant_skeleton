"""Stable v1 reminder-rule extension surface.

Reminder rules are advisory bricks: they inspect public Task/Event objects and
return platform-neutral NotificationRequest values. Delivery and Task mutation
remain owned by Core services.
"""
from ...internal.reminders.engine import NotificationRequest
from ...internal.reminders.rules import reminder_rule

__all__ = ["NotificationRequest", "reminder_rule"]
