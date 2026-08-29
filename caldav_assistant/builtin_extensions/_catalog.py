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
    }
)


__all__ = ["OFFICIAL_EXTENSION_CATALOG"]
