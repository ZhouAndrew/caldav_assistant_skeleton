from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.api import ActionResult, Event, Task
from caldav_assistant.internal.thunderbird import native_host


class Tasks:
    def __init__(self):
        self.calls = []
        self.task = Task(id="t1", summary="Report", status="IN-PROCESS")

    def list(self):
        return [self.task]

    def start(self, task, *, at=None):
        self.calls.append(("start", task, at))
        return ActionResult(True, affected=self.task)

    def resume(self, task, *, at=None):
        self.calls.append(("resume", task, at))
        return ActionResult(True, affected=self.task)

    def pause(self, task, *, at=None):
        self.calls.append(("pause", task, at))
        return ActionResult(True, affected=self.task)

    def cancel(self, task, *, at=None):
        self.calls.append(("cancel", task, at))
        return ActionResult(True, affected=self.task)

    def complete(self, task, *, at=None):
        self.calls.append(("complete", task, at))
        return ActionResult(True, affected=self.task)


class Session:
    def __init__(self):
        self.current = None
        self.paused = ["t1"]

    def current_task_id(self):
        return self.current

    def paused_task_ids(self):
        return tuple(self.paused)


class WordPress:
    def __init__(self):
        self.calls = []

    def pending(self):
        return []

    def log(self, text, **metadata):
        self.calls.append(("log", text, metadata))
        return ActionResult(True, message="saved")

    def attach_file(self, path, **metadata):
        self.calls.append(("attach", str(path), metadata))
        return ActionResult(True, message="attached")


class Runtime:
    def __init__(self):
        self.calls = []

    def call(self, method, **payload):
        self.calls.append((method, payload))
        if method == "worklog.open_for":
            return Event(id="w-open", summary="Work")
        if method == "wordpress.flush":
            return {"sent": 1, "failed": 0, "pending": 0}
        return []


def bridge():
    ctx = SimpleNamespace(
        tasks=Tasks(),
        session=Session(),
        wordpress=WordPress(),
    )
    app = SimpleNamespace(ctx=ctx, runtime=Runtime())
    return native_host.ThunderbirdBridge(app), ctx, app.runtime


def test_start_button_resumes_a_paused_task_without_exposing_a_fifth_action():
    value, ctx, _ = bridge()

    result = value.handle(
        {
            "type": "action",
            "action": "start",
            "task_id": "t1",
            "at": "2026-09-27T10:30:00+08:00",
        }
    )

    assert result["ok"] is True
    assert ctx.tasks.calls == [
        ("resume", "t1", "2026-09-27T10:30:00+08:00"),
    ]


def test_four_user_actions_are_forwarded_with_the_user_time():
    value, ctx, _ = bridge()
    ctx.session.paused = []

    for action in ("start", "pause", "cancel", "complete"):
        value.handle(
            {
                "type": "action",
                "action": action,
                "task_id": "t1",
                "at": "2026-09-27T14:25:00+08:00",
            }
        )

    assert [row[0] for row in ctx.tasks.calls] == [
        "start",
        "pause",
        "cancel",
        "complete",
    ]
    assert all(row[2] == "2026-09-27T14:25:00+08:00" for row in ctx.tasks.calls)


def test_attachment_is_persisted_and_defaults_calendar_post_link_on(tmp_path, monkeypatch):
    value, ctx, runtime = bridge()
    monkeypatch.setattr(native_host, "_ATTACHMENT_ROOT", tmp_path)

    result = value.handle(
        {
            "type": "attachment",
            "name": "result.png",
            "mime_type": "image/png",
            "data_base64": "aW1hZ2U=",
            "task_id": "t1",
            "calendar_link": True,
            "calendar_attachment_link": False,
        }
    )

    assert result["ok"] is True
    operation, path, metadata = ctx.wordpress.calls[-1]
    assert operation == "attach"
    assert metadata["_calendar_link"] is True
    assert metadata["_calendar_attachment_link"] is False
    assert metadata["_work_event_id"] == "w-open"
    assert metadata["filename"] == "result.png"
    assert (tmp_path / path.split("/")[-1]).read_bytes() == b"image"
    assert runtime.calls[0][0] == "worklog.open_for"
