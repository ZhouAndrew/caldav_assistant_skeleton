from __future__ import annotations

import pytest

from caldav_assistant.api.v1.errors import ConflictError, NotFoundError
from caldav_assistant.internal.commands import CommandRegistry, CommandService


def test_service_is_the_single_execution_facade_and_forwards_arguments():
    registry = CommandRegistry()
    service = CommandService(registry)
    calls = []

    def handler(task, *, force=False):
        calls.append((task, force))
        return "done"

    service.register_builtin("done", handler)

    assert service.run("DONE", "task-1", force=True) == "done"
    assert calls == [("task-1", True)]
    assert service.execute("done", "task-2") == "done"
    assert service("done", "task-3") == "done"


def test_service_registration_helpers_still_use_one_registry():
    service = CommandService(CommandRegistry())

    builtin = service.register_builtin("today", lambda: 1)
    user = service.register_user("school", lambda: 2)
    extension = service.register_extension("urgent", lambda: 3, extension="demo")

    assert builtin.protected is True
    assert builtin.source == "builtin"
    assert user.source == "user"
    assert extension.source == "extension:demo"
    assert service.names() == ("today", "school", "urgent")


def test_service_does_not_swallow_handler_errors():
    service = CommandService(CommandRegistry())

    class DomainFailure(RuntimeError):
        pass

    def fail():
        raise DomainFailure("visible")

    service.register("broken", fail)

    with pytest.raises(DomainFailure, match="visible"):
        service.run("broken")


def test_service_keeps_conflict_and_missing_errors_visible():
    service = CommandService(CommandRegistry())
    service.register_builtin("today", lambda: 1)

    with pytest.raises(ConflictError):
        service.register_extension("today", lambda: 2, extension="demo")
    with pytest.raises(NotFoundError):
        service.run("missing")
