from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repair_recurring_vtodos.py"
SPEC = importlib.util.spec_from_file_location("repair_recurring_vtodos", SCRIPT)
assert SPEC and SPEC.loader
repair = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = repair
SPEC.loader.exec_module(repair)


RAW = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VTODO\r
UID:anki-series-1\r
SUMMARY:Anki\r
DTSTART:20260920T090000\r
DUE:20260920T100000\r
RRULE:FREQ=DAILY\r
STATUS:COMPLETED\r
PERCENT-COMPLETE:100\r
COMPLETED:20260927T010000Z\r
CATEGORIES:scheduled-task\r
END:VTODO\r
BEGIN:VTODO\r
UID:anki-series-1\r
RECURRENCE-ID:20260926T090000\r
SUMMARY:Anki\r
STATUS:COMPLETED\r
END:VTODO\r
BEGIN:VTODO\r
UID:anki-series-1\r
RECURRENCE-ID:20260927T090000\r
SUMMARY:Anki\r
STATUS:COMPLETED\r
END:VTODO\r
END:VCALENDAR\r
"""


def fake_task(*, uid: str = "anki-series-1", raw: bytes = RAW):
    return SimpleNamespace(
        id=uid,
        summary="Anki",
        status="COMPLETED",
        completed=True,
        completed_at=None,
        start=None,
        due=None,
        categories=["scheduled-task"],
        raw=raw,
        _caldav_collection_url="http://example.test/tasks/",
        _caldav_url=f"http://example.test/tasks/{uid}.ics",
        _caldav_etag='"etag-1"',
    )


def test_snapshot_exposes_recurrence_parent_and_exceptions(tmp_path: Path):
    row = repair._snapshot(fake_task(), tmp_path, 1)

    assert row.uid == "anki-series-1"
    assert row.status == "COMPLETED"
    assert row.rrule == "FREQ=DAILY"
    assert row.parent_count == 1
    assert row.exception_count == 2
    assert len(row.recurrence_ids) == 2
    assert Path(row.raw_backup).read_bytes() == RAW
    assert len(row.raw_sha256) == 64


def test_one_task_refuses_ambiguous_uid():
    tasks = [fake_task(), fake_task()]
    with pytest.raises(SystemExit, match="Refusing an ambiguous write"):
        repair._one_task(tasks, "anki-series-1")


def test_audit_mode_never_writes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys):
    task = fake_task()
    calls = []

    class Tasks:
        def list(self):
            return [task]

        def update(self, *args, **kwargs):
            calls.append(("update", args, kwargs))
            raise AssertionError("audit must not update")

        def delete(self, *args, **kwargs):
            calls.append(("delete", args, kwargs))
            raise AssertionError("audit must not delete")

    app = SimpleNamespace(ctx=SimpleNamespace(tasks=Tasks()))
    monkeypatch.setattr(repair, "build_service_application", lambda: app)

    rc = repair.main([
        "--summary",
        "Anki",
        "--output-dir",
        str(tmp_path / "audit"),
    ])

    assert rc == 0
    assert calls == []
    report = (tmp_path / "audit" / "report.json").read_text(encoding="utf-8")
    assert "anki-series-1" in report
    assert "AUDIT ONLY" in capsys.readouterr().out


def test_write_requires_apply(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys):
    task = fake_task()
    calls = []

    class Tasks:
        def list(self):
            return [task]

        def update(self, *args, **kwargs):
            calls.append(("update", args, kwargs))
            return SimpleNamespace(affected=task)

        def delete(self, *args, **kwargs):
            calls.append(("delete", args, kwargs))
            return SimpleNamespace(affected=task)

    app = SimpleNamespace(ctx=SimpleNamespace(tasks=Tasks()))
    monkeypatch.setattr(repair, "build_service_application", lambda: app)

    rc = repair.main([
        "--summary",
        "Anki",
        "--repair-status-uid",
        "anki-series-1",
        "--output-dir",
        str(tmp_path / "dry-run"),
    ])

    assert rc == 0
    assert calls == []
    assert "DRY RUN" in capsys.readouterr().out


def test_apply_repairs_status_after_backup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    task = fake_task()
    calls = []

    class Tasks:
        def list(self):
            return [task]

        def update(self, selected, **changes):
            backup_files = list((tmp_path / "apply").glob("*.ics"))
            assert backup_files, "backup must exist before write"
            calls.append(("update", selected.id, changes))
            affected = fake_task()
            affected.status = "NEEDS-ACTION"
            affected.completed = False
            return SimpleNamespace(affected=affected)

        def delete(self, *args, **kwargs):
            raise AssertionError("unexpected delete")

    app = SimpleNamespace(ctx=SimpleNamespace(tasks=Tasks()))
    monkeypatch.setattr(repair, "build_service_application", lambda: app)

    rc = repair.main([
        "--summary",
        "Anki",
        "--repair-status-uid",
        "anki-series-1",
        "--apply",
        "--output-dir",
        str(tmp_path / "apply"),
    ])

    assert rc == 0
    assert calls == [
        (
            "update",
            "anki-series-1",
            {
                "status": "NEEDS-ACTION",
                "completed": False,
                "completed_at": None,
            },
        )
    ]
