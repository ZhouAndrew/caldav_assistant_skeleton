"""Notification service and replaceable OS adapter boundary."""

from .adapter import NotificationAdapter
from .service import NotificationService

__all__ = ["NotificationAdapter", "NotificationService"]
