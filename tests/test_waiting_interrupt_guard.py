from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.internal.cli import waiting_interrupt_guard


def _module(actions):
    calls = []
    attempts = {"count": 0}
    target = SimpleNamespace(kind="task", current_work=True)

    def waiting_mode(app):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise KeyboardInterrupt
        return "wait"

    def wait_interrupt(app, current):
        calls.append(current)
        return actions.pop(0)

    module = SimpleNamespace(
        _waiting_mode=waiting_mode,
        legacy=SimpleNamespace(_monitor_target=lambda app: target),
        conversation=SimpleNamespace(
            _wait_interrupt=wait_interrupt,
            _show=lambda app, value="": None,
        ),
    )
    return module, target, calls, attempts


def test_ctrl_c_during_waiting_initialization_opens_normal_task_menu_and_can_leave():
    module, target, calls, attempts = _module(["console"])
    waiting_interrupt_guard.install(module)

    result = module._waiting_mode(SimpleNamespace())

    assert result == "console"
    assert calls == [target]
    assert attempts["count"] == 1


def test_continue_waiting_retries_initialization_after_early_ctrl_c():
    module, target, calls, attempts = _module(["wait"])
    waiting_interrupt_guard.install(module)

    result = module._waiting_mode(SimpleNamespace())

    assert result == "wait"
    assert calls == [target]
    assert attempts["count"] == 2
