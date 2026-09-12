from __future__ import annotations

from caldav_assistant.internal.runtime.cli import BackgroundActions
from caldav_assistant.internal.runtime.process_lifecycle import wait_for_process_exit


def test_wait_for_process_exit_uses_bounded_liveness_polling():
    states = iter([True, True, False])
    seen = []

    def alive(pid):
        seen.append(pid)
        return next(states)

    assert wait_for_process_exit(
        321,
        timeout=0.1,
        poll_interval=0.001,
        alive=alive,
    ) is True
    assert seen == [321, 321, 321]


def test_background_stop_waits_for_pid_before_reporting_stopped():
    class Runtime:
        running = True

        def status(self):
            return {
                "status": "running" if self.running else "stopped",
                "pid": 4321 if self.running else None,
            }

        def stop(self):
            self.running = False
            return True

    class Autostart:
        def is_enabled(self):
            return False

    waited = []

    def waiter(pid, *, timeout):
        waited.append((pid, timeout))
        return True

    actions = BackgroundActions(
        Runtime(),
        autostart=Autostart(),
        process_waiter=waiter,
    )
    result = actions.command("stop")

    assert "Background service: Stopped" in result
    assert waited == [(4321, 5.0)]


def test_background_restart_waits_for_old_pid_before_starting_new_process():
    events = []

    class Runtime:
        running = True

        def status(self):
            return {
                "status": "running" if self.running else "stopped",
                "pid": 1001 if self.running else None,
            }

        def stop(self):
            events.append("stop")
            self.running = False
            return True

        def ensure_running(self):
            events.append("start")
            self.running = True
            return {"status": "running", "pid": 1002}

    class Autostart:
        def is_enabled(self):
            return False

    def waiter(pid, *, timeout):
        events.append(f"wait:{pid}")
        return True

    actions = BackgroundActions(
        Runtime(),
        autostart=Autostart(),
        process_waiter=waiter,
    )
    result = actions.command("restart")

    assert "Background service: Running" in result
    assert events == ["stop", "wait:1001", "start"]
