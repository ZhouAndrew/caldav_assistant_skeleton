from __future__ import annotations

import pytest

from caldav_assistant.api.v1.errors import ConflictError, NotFoundError, ValidationError
from caldav_assistant.internal.commands import CommandRegistry


def noop(*args, **kwargs):
    return args, kwargs


def test_builtin_user_and_extension_commands_share_one_namespace():
    registry = CommandRegistry()
    registry.register("today", noop, source="builtin", protected=True)
    registry.register("school", noop, source="user")
    registry.register("urgent", noop, source="extension:demo")

    assert registry.names() == ("today", "school", "urgent")
    assert [entry.source for entry in registry.entries()] == [
        "builtin",
        "user",
        "extension:demo",
    ]


def test_lookup_is_case_insensitive_and_aliases_resolve_to_same_entry():
    registry = CommandRegistry()
    entry = registry.register("today", noop, aliases=["tod", "今天"])

    assert registry.resolve("TODAY") is entry
    assert registry.resolve("Tod") is entry
    assert registry.resolve("今天") is entry
    assert registry.get("today") is noop


def test_conflicts_are_never_silent_for_canonical_names_or_aliases():
    registry = CommandRegistry()
    registry.register("school", noop, aliases=["class"])

    with pytest.raises(ConflictError):
        registry.register("school", lambda: None)
    with pytest.raises(ConflictError):
        registry.register("class", lambda: None)
    with pytest.raises(ConflictError):
        registry.register("other", lambda: None, aliases=["school"])


def test_explicit_override_replaces_ordinary_command_atomically():
    registry = CommandRegistry()
    old = lambda: "old"
    new = lambda: "new"
    registry.register("school", old, aliases=["class"])

    entry = registry.register(
        "school",
        new,
        aliases=["campus"],
        override=True,
    )

    assert registry.get("school")() == "new"
    assert registry.get("campus")() == "new"
    assert entry.aliases == ("campus",)
    with pytest.raises(NotFoundError):
        registry.get("class")


def test_protected_command_requires_second_explicit_permission_to_override_or_remove():
    registry = CommandRegistry()
    registry.register("done", noop, protected=True)

    with pytest.raises(ConflictError):
        registry.register("done", lambda: None, override=True)
    with pytest.raises(ConflictError):
        registry.unregister("done")

    replacement = lambda: "replacement"
    registry.register(
        "done",
        replacement,
        protected=True,
        override=True,
        allow_protected_override=True,
    )
    assert registry.get("done") is replacement

    registry.unregister("done", allow_protected=True)
    with pytest.raises(NotFoundError):
        registry.get("done")


def test_failed_override_does_not_damage_existing_registration():
    registry = CommandRegistry()
    original = lambda: "safe"
    registry.register("school", original, aliases=["class"])
    registry.register("today", noop)

    with pytest.raises(ConflictError):
        registry.register(
            "school",
            lambda: "bad",
            aliases=["today"],
            override=True,
        )

    assert registry.get("school") is original
    assert registry.get("class") is original


def test_validation_and_missing_commands_use_stable_public_errors():
    registry = CommandRegistry()

    with pytest.raises(ValidationError):
        registry.register(" ", noop)
    with pytest.raises(ValidationError):
        registry.register("two words", noop)
    with pytest.raises(ValidationError):
        registry.register("ok", object())
    with pytest.raises(NotFoundError):
        registry.get("missing")


def test_registry_snapshots_do_not_expose_mutable_metadata():
    registry = CommandRegistry()
    source = {"extension": {"name": "demo"}}
    entry = registry.register("demo", noop, metadata=source)
    source["new"] = True

    assert "new" not in entry.metadata
    with pytest.raises(TypeError):
        entry.metadata["x"] = 1
