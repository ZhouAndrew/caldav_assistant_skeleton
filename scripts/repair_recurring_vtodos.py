#!/usr/bin/env python3
"""Audit and safely repair duplicate recurring CalDAV VTODO series.

Default mode is READ-ONLY. It scans the configured CalDAV Task collection through
CalDAV Assistant, writes an offline raw-ICS backup + JSON report, and prints the
UID/RRULE/status/exception structure for exact-summary matches.

Writes require both an explicit operation and --apply. There is deliberately no
"guess the right series" mode: the operator must name the UID to keep/repair/delete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from caldav_assistant.internal.bootstrap import build_service_application


@dataclass
class TodoSnapshot:
    uid: str
    summary: str
    status: str
    completed: bool
    completed_at: str | None
    start: str | None
    due: str | None
    categories: list[str]
    collection_url: str
    resource_url: str
    etag: str | None
    rrule: str | None
    parent_count: int
    exception_count: int
    recurrence_ids: list[str]
    sequence: str | None
    dtstamp: str | None
    last_modified: str | None
    raw_sha256: str
    raw_backup: str


def _value(value: Any) -> str | None:
    if value is None:
        return None
    dt = getattr(value, "dt", None)
    if dt is not None:
        value = dt
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _raw_bytes(raw: Any) -> bytes:
    if raw is None:
        return b""
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, str):
        return raw.encode("utf-8", errors="surrogateescape")
    to_ical = getattr(raw, "to_ical", None)
    if callable(to_ical):
        value = to_ical()
        return value if isinstance(value, bytes) else str(value).encode()
    return str(raw).encode("utf-8", errors="replace")


def _ical_text(prop: Any) -> str | None:
    if prop is None:
        return None
    to_ical = getattr(prop, "to_ical", None)
    if callable(to_ical):
        value = to_ical()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)
    return str(prop)


def _parse_vtodos(raw: bytes) -> list[Any]:
    if not raw:
        return []
    try:
        from icalendar import Calendar
    except ImportError as exc:
        raise SystemExit(
            "ERROR: Python package 'icalendar' is unavailable. "
            "Reinstall CalDAV Assistant dependencies first."
        ) from exc
    try:
        cal = Calendar.from_ical(raw)
    except Exception as exc:
        raise RuntimeError(f"Could not parse raw iCalendar data: {exc}") from exc
    return [component for component in cal.walk() if getattr(component, "name", "") == "VTODO"]


def _safe_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return clean[:80] or "todo"


def _default_output_dir(summary: str) -> Path:
    desktop = Path.home() / "Desktop"
    base = desktop if desktop.is_dir() else Path.home()
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return base / f"caldav-recurring-audit-{_safe_name(summary)}-{stamp}"


def _snapshot(task: Any, backup_dir: Path, index: int) -> TodoSnapshot:
    raw = _raw_bytes(getattr(task, "raw", None))
    components = _parse_vtodos(raw)
    parents = [c for c in components if c.get("RECURRENCE-ID") is None]
    exceptions = [c for c in components if c.get("RECURRENCE-ID") is not None]
    parent = parents[0] if parents else (components[0] if components else None)

    uid = str(getattr(task, "id", "") or (parent.get("UID") if parent else "") or "")
    summary = str(getattr(task, "summary", "") or "")
    filename = f"{index:02d}-{_safe_name(summary)}-{_safe_name(uid)}.ics"
    raw_path = backup_dir / filename
    raw_path.write_bytes(raw)

    recurrence_ids = [
        _ical_text(component.get("RECURRENCE-ID")) or ""
        for component in exceptions
    ]

    return TodoSnapshot(
        uid=uid,
        summary=summary,
        status=str(getattr(task, "status", "") or ""),
        completed=bool(getattr(task, "completed", False)),
        completed_at=_value(getattr(task, "completed_at", None)),
        start=_value(getattr(task, "start", None)),
        due=_value(getattr(task, "due", None)),
        categories=list(getattr(task, "categories", ()) or ()),
        collection_url=str(getattr(task, "_caldav_collection_url", "") or ""),
        resource_url=str(getattr(task, "_caldav_url", "") or ""),
        etag=(
            None
            if getattr(task, "_caldav_etag", None) is None
            else str(getattr(task, "_caldav_etag"))
        ),
        rrule=_ical_text(parent.get("RRULE")) if parent is not None else None,
        parent_count=len(parents),
        exception_count=len(exceptions),
        recurrence_ids=recurrence_ids,
        sequence=_ical_text(parent.get("SEQUENCE")) if parent is not None else None,
        dtstamp=_ical_text(parent.get("DTSTAMP")) if parent is not None else None,
        last_modified=_ical_text(parent.get("LAST-MODIFIED")) if parent is not None else None,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        raw_backup=str(raw_path),
    )


def _print_table(rows: list[TodoSnapshot]) -> None:
    print()
    print(f"Matched recurring-series candidates: {len(rows)}")
    print("=" * 96)
    for index, row in enumerate(rows, 1):
        print(f"[{index}] {row.summary!r}")
        print(f"    UID        : {row.uid}")
        print(f"    Status     : {row.status}  completed={row.completed}  completed_at={row.completed_at}")
        print(f"    DTSTART    : {row.start}")
        print(f"    DUE        : {row.due}")
        print(f"    RRULE      : {row.rrule}")
        print(f"    Categories : {', '.join(row.categories) if row.categories else '(none)'}")
        print(f"    Parent/Ex  : {row.parent_count} parent, {row.exception_count} exception(s)")
        if row.recurrence_ids:
            for rid in row.recurrence_ids[:8]:
                print(f"                 RECURRENCE-ID {rid}")
            if len(row.recurrence_ids) > 8:
                print(f"                 ... {len(row.recurrence_ids) - 8} more")
        print(f"    Collection : {row.collection_url}")
        print(f"    Resource   : {row.resource_url}")
        print(f"    Backup     : {row.raw_backup}")
        print(f"    SHA256     : {row.raw_sha256}")
        print("-" * 96)


def _one_task(tasks: list[Any], uid: str) -> Any:
    matches = [task for task in tasks if str(getattr(task, "id", "")) == uid]
    if not matches:
        raise SystemExit(f"ERROR: UID not found among exact-summary matches: {uid}")
    if len(matches) != 1:
        raise SystemExit(
            f"ERROR: UID {uid!r} matched {len(matches)} resources. "
            "Refusing an ambiguous write."
        )
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit/repair duplicate recurring VTODOs without guessing which series is canonical."
    )
    parser.add_argument("--summary", default="Anki", help="Exact title, case-insensitive (default: Anki)")
    parser.add_argument("--output-dir", type=Path, help="Backup/report directory")
    parser.add_argument(
        "--repair-status-uid",
        help="Clear accidental parent-level completion on exactly this UID (sets NEEDS-ACTION, completed=False).",
    )
    parser.add_argument(
        "--delete-uid",
        action="append",
        default=[],
        help="Delete exactly this duplicate series UID after backup. Repeat for multiple UIDs.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform requested writes. Without this flag all writes are dry-run only.",
    )
    args = parser.parse_args(argv)

    output_dir = (args.output_dir or _default_output_dir(args.summary)).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    app = build_service_application()
    all_tasks = list(app.ctx.tasks.list() or ())
    needle = args.summary.strip().casefold()
    matches = [task for task in all_tasks if str(getattr(task, "summary", "")).strip().casefold() == needle]

    snapshots = [_snapshot(task, output_dir, index) for index, task in enumerate(matches, 1)]
    report = {
        "created_at": datetime.now().astimezone().isoformat(),
        "summary_filter": args.summary,
        "match_count": len(snapshots),
        "items": [asdict(item) for item in snapshots],
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _print_table(snapshots)
    print(f"JSON report  : {report_path}")
    print(f"Raw backup   : {output_dir}")
    print()

    requested_write = bool(args.repair_status_uid or args.delete_uid)
    if not requested_write:
        print("AUDIT ONLY: no CalDAV data changed.")
        return 0

    if args.repair_status_uid:
        _one_task(matches, args.repair_status_uid)
        print(
            "PLAN: repair UID "
            f"{args.repair_status_uid}: STATUS -> NEEDS-ACTION; COMPLETED removed; PERCENT-COMPLETE -> 0"
        )

    for uid in args.delete_uid:
        _one_task(matches, uid)
        if args.repair_status_uid and uid == args.repair_status_uid:
            raise SystemExit("ERROR: the same UID cannot be repaired and deleted in one run")
        print(f"PLAN: delete duplicate recurring series UID {uid}")

    if not args.apply:
        print()
        print("DRY RUN: no CalDAV data changed. Re-run with --apply only after reviewing the backup/report.")
        return 0

    # All raw ICS resources were backed up before the first write.
    if args.repair_status_uid:
        task = _one_task(matches, args.repair_status_uid)
        result = app.ctx.tasks.update(
            task,
            status="NEEDS-ACTION",
            completed=False,
            completed_at=None,
        )
        affected = getattr(result, "affected", None)
        print(
            "APPLIED: repaired "
            f"{getattr(affected, 'id', args.repair_status_uid)} -> "
            f"{getattr(affected, 'status', 'NEEDS-ACTION')}"
        )

    for uid in args.delete_uid:
        task = _one_task(matches, uid)
        app.ctx.tasks.delete(task)
        print(f"APPLIED: deleted duplicate series UID {uid}")

    print()
    print("Writes completed. Raw ICS backup remains at:")
    print(f"  {output_dir}")
    print("Refresh/sync Thunderbird before evaluating Today/All.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
