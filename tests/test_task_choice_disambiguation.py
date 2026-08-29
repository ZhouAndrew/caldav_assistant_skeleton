from __future__ import annotations

from datetime import datetime, timezone

from caldav_assistant.api import Task
from caldav_assistant.internal.prompts.kit import PromptKit
from caldav_assistant.internal.prompts.task_labels import deduplicate_tasks, task_labeler


class CaptureMenu:
    def __init__(self):
        self.items = []
        self.labels = []

    def choose(self, title, items, **options):
        self.items = list(items)
        label = options.get("item_label", str)
        self.labels = [label(item) for item in self.items]
        return self.items[0] if self.items else None

    def choose_many(self, title, items, **options):
        self.items = list(items)
        label = options.get("item_label", str)
        self.labels = [label(item) for item in self.items]
        return list(self.items)

    def _read(self, prompt):
        return "0"

    def _write(self, value=""):
        return None


class Tasks:
    def __init__(self, items):
        self.items = list(items)

    def list(self, **filters):
        return list(self.items)


class Temporal:
    pass


def task(uid, *, due_hour, categories=None):
    return Task(
        id=uid,
        summary="Anki",
        due=datetime(2026, 8, 29, due_hour, 0, tzinfo=timezone.utc),
        categories=list(categories or []),
        status="IN-PROCESS",
    )


def test_duplicate_rows_with_same_uid_are_removed_but_same_names_with_different_uids_remain():
    first = task("abc111", due_hour=17)
    duplicate_row = task("abc111", due_hour=17)
    second = task("abc222", due_hour=20)

    result = deduplicate_tasks([first, duplicate_row, second])

    assert [item.id for item in result] == ["abc111", "abc222"]


def test_same_named_tasks_get_human_context_and_unique_uid_prefixes():
    items = [
        task("abc111", due_hour=17, categories=["Projects"]),
        task("abc222", due_hour=20, categories=["Study"]),
        task("xyz333", due_hour=20, categories=["Study"]),
    ]

    tasks, label = task_labeler(items)
    labels = [label(item) for item in tasks]

    assert len(labels) == 3
    assert len(set(labels)) == 3
    assert all(text.startswith("Anki · due 2026-08-29") for text in labels)
    assert "Projects" in labels[0]
    assert "Study" in labels[1]
    assert all("#" in text for text in labels)
    assert labels[0].endswith("#abc1")
    assert labels[1].endswith("#abc2")
    assert labels[2].endswith("#xyz3")


def test_unique_task_name_stays_compact_without_uid_noise():
    item = Task(id="long-uid-123", summary="Write report", due=datetime(2026, 8, 30, 9, 0))

    tasks, label = task_labeler([item])

    assert label(tasks[0]) == "Write report · due 2026-08-30 09:00"
    assert "#" not in label(tasks[0])


def test_promptkit_choose_overrides_title_only_labels_for_task_objects():
    menu = CaptureMenu()
    first = task("same-prefix-a", due_hour=17)
    second = task("same-prefix-b", due_hour=17)
    ui = PromptKit(None, menu, Temporal())

    chosen = ui.choose(
        "Resume which paused task?",
        [first, second],
        item_label=lambda item: item.summary,
    )

    assert chosen is first
    assert len(menu.labels) == 2
    assert len(set(menu.labels)) == 2
    assert all(label.startswith("Anki · due") for label in menu.labels)
    assert all("#same-prefix-" in label for label in menu.labels)


def test_choose_task_deduplicates_same_uid_before_numbering_menu():
    menu = CaptureMenu()
    first = task("t-1", due_hour=17)
    duplicate = task("t-1", due_hour=17)
    second = task("t-2", due_hour=20)
    ui = PromptKit(None, menu, Temporal(), tasks=Tasks([first, duplicate, second]))

    ui.choose_task()

    assert [item.id for item in menu.items] == ["t-1", "t-2"]
    assert len(menu.labels) == 2
    assert len(set(menu.labels)) == 2


def test_zero_keeps_promptkit_cancel_semantics():
    menu = CaptureMenu()
    ui = PromptKit(None, menu, Temporal())

    assert ui.ask_yes_no("Continue?") is None
