"""Metadata for official extensions bundled with CalDAV Assistant.

The catalog is presentation metadata only.  ExtensionManager still owns discovery,
loading, enable/disable persistence, error isolation, and command ownership.
"""
from __future__ import annotations

from types import MappingProxyType


OFFICIAL_EXTENSION_CATALOG = MappingProxyType(
    {
        "software_intro": MappingProxyType(
            {
                "title": "Software introduction / first-run setup",
                "description": (
                    "Guides first-time CalDAV configuration and shows the normal "
                    "Task/Event command model after setup."
                ),
                "default_enabled": True,
            }
        ),
        "wordpress_work_session_log": MappingProxyType(
            {
                "title": "WordPress work-session log",
                "description": (
                    "Writes Task start/resume work-session transitions through the "
                    "WordPress/Outbox service without making WordPress part of Task "
                    "business logic."
                ),
                "default_enabled": True,
            }
        ),
        "developer_tools": MappingProxyType(
            {
                "title": "Developer terminal tools",
                "description": (
                    "Adds clear plus a foreground shell command for temporarily "
                    "running external debugging tools and interactive shells."
                ),
                "default_enabled": False,
            }
        ),
    }
)


__all__ = ["OFFICIAL_EXTENSION_CATALOG"]
