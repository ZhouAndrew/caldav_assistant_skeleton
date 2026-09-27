"""Secondary WordPress -> CalDAV Work VEVENT link projection.

The WordPress Outbox remains authoritative for delivery retry.  This observer runs
only after WordPress accepts a log/media operation and idempotently adds the resulting
permalink to the already-authoritative Work VEVENT.  Failure is allowed to keep the
Outbox item pending so a later retry can finish the projection without changing Task
state or work timestamps.
"""
from __future__ import annotations

from typing import Any


class WordPressCalendarLinker:
    def __init__(self, worklog: Any) -> None:
        self.worklog = worklog

    @staticmethod
    def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
        args = payload.get("args")
        if not isinstance(args, dict):
            return {}
        metadata = args.get("metadata")
        return metadata if isinstance(metadata, dict) else {}

    def after_delivery(
        self,
        operation: str,
        result: Any,
        payload: dict[str, Any],
    ) -> None:
        metadata = self._metadata(payload)
        if not bool(metadata.get("_calendar_link", False)):
            return

        event_id = str(metadata.get("_work_event_id") or "").strip()
        if not event_id or not isinstance(result, dict):
            return
        post_url = str(result.get("post_url") or "").strip()
        if not post_url:
            return

        attachment_urls: list[str] = []
        if (
            operation == "attach_file"
            and bool(metadata.get("_calendar_attachment_link", False))
        ):
            attachment_url = str(result.get("url") or "").strip()
            if attachment_url:
                attachment_urls.append(attachment_url)

        self.worklog.link_wordpress(
            event_id,
            post_url,
            attachment_urls=attachment_urls,
        )


__all__ = ["WordPressCalendarLinker"]
