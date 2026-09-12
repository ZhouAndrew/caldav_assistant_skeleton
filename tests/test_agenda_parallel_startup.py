from __future__ import annotations

from threading import Barrier

from caldav_assistant.internal.agenda.service import AgendaService


class BarrierTasks:
    def __init__(self, barrier):
        self.barrier = barrier

    def list(self, **filters):
        self.barrier.wait(timeout=2)
        return []


class BarrierEvents:
    def __init__(self, barrier):
        self.barrier = barrier

    def list(self, **filters):
        self.barrier.wait(timeout=2)
        return []


class BuildEngine:
    def build(self, tasks, events, **kwargs):
        return type("Agenda", (), {"items": ()})()

    def candidates(self, tasks, events):
        return ()


class NextEngine:
    def choose(self, agenda, **kwargs):
        return None


class BarrierSession:
    def __init__(self, barrier):
        self.barrier = barrier
        self.received_work_facts = None

    def startup_work_facts(self):
        self.barrier.wait(timeout=2)
        return {"current_task_id": None, "worked_task_ids": ()}

    def startup_snapshot(self, tasks, *, work_facts=None):
        self.received_work_facts = work_facts
        return {
            "current_task_id": None,
            "current_task": None,
            "paused_task_ids": (),
        }


def test_today_runs_independent_task_and_event_reads_concurrently():
    barrier = Barrier(2)
    service = AgendaService(
        BarrierTasks(barrier),
        BarrierEvents(barrier),
        BuildEngine(),
        NextEngine(),
        {},
    )

    agenda = service.today()
    assert agenda.items == ()


def test_startup_overlaps_task_event_and_work_reads():
    barrier = Barrier(3)
    session = BarrierSession(barrier)
    service = AgendaService(
        BarrierTasks(barrier),
        BarrierEvents(barrier),
        BuildEngine(),
        NextEngine(),
        {},
        session=session,
    )

    result = service.startup_snapshot(days=1, kind="task")

    assert result["agenda"].items == ()
    assert result["current_task"] is None
    assert session.received_work_facts == {
        "current_task_id": None,
        "worked_task_ids": (),
    }
