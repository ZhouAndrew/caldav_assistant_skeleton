from datetime import date, datetime

from caldav_assistant.internal.prompts.pickers import (
    DateCursor,
    DatePickerController,
    ScrollCursor,
    TaskPickerController,
    task_matches_date,
)


class Task:
    def __init__(self, summary, *, due=None, start=None, task_id=""):
        self.summary = summary
        self.due = due
        self.start = start
        self.id = task_id
        self.status = "NEEDS-ACTION"
        self.categories = []


def test_date_cursor_moves_days_weeks_and_months_without_invalid_dates():
    cursor = DateCursor(selected=date(2026, 1, 31), today=date(2026, 1, 15))

    cursor.move_days(1)
    assert cursor.selected == date(2026, 2, 1)

    cursor.move_weeks(1)
    assert cursor.selected == date(2026, 2, 8)

    cursor.selected = date(2026, 3, 31)
    cursor.move_months(-1)
    assert cursor.selected == date(2026, 2, 28)

    cursor.reset_today()
    assert cursor.selected == date(2026, 1, 15)


def test_date_picker_view_marks_dates_without_knowing_task_business():
    controller = DatePickerController(
        date(2026, 9, 26),
        today=date(2026, 9, 26),
    )

    view = controller.view(
        "Calendar",
        marked_dates=(date(2026, 9, 26), date(2026, 9, 28)),
    )

    assert view.selected == date(2026, 9, 26)
    assert view.today == date(2026, 9, 26)
    assert date(2026, 9, 28) in view.marked_dates
    assert any(date(2026, 9, 26) in week for week in view.weeks)


def test_scroll_cursor_keeps_selected_item_visible():
    cursor = ScrollCursor(list(range(20)), page_size=5)

    cursor.move(7)
    assert cursor.selected == 7
    assert cursor.offset == 3

    cursor.page(1)
    assert cursor.selected == 12
    assert cursor.offset == 8

    cursor.page(-1)
    assert cursor.selected == 7
    assert cursor.offset == 7


def test_task_date_match_accepts_due_or_start_and_datetime_wall_date():
    selected = date(2026, 9, 26)

    assert task_matches_date(Task("Due", due=selected), selected)
    assert task_matches_date(
        Task("Start", start=datetime(2026, 9, 26, 8, 30)),
        selected,
    )
    assert not task_matches_date(Task("Other", due=date(2026, 9, 27)), selected)


def test_task_picker_defaults_to_selected_date_and_refreshes_when_date_changes():
    today = date(2026, 9, 26)
    tasks = [
        Task("Today A", due=today, task_id="a"),
        Task("Today B", start=datetime(2026, 9, 26, 12, 0), task_id="b"),
        Task("Tomorrow", due=date(2026, 9, 27), task_id="c"),
        Task("Undated", task_id="d"),
    ]
    controller = TaskPickerController(
        tasks,
        labeler=lambda task: task.summary,
        selected_date=today,
        today=today,
        page_size=8,
    )

    view = controller.view()
    assert view.tasks.labels == ("Today A", "Today B")
    assert controller.selected_task.summary == "Today A"

    controller.move_task(1)
    assert controller.selected_task.summary == "Today B"

    controller.move_date_days(1)
    assert controller.date.selected == date(2026, 9, 27)
    assert controller.view().tasks.labels == ("Tomorrow",)
    assert controller.selected_task.summary == "Tomorrow"
    assert date(2026, 9, 27) in controller.view().calendar.marked_dates


def test_task_picker_search_only_filters_tasks_on_selected_date():
    today = date(2026, 9, 26)
    tasks = [
        Task("Math review", due=today, task_id="a"),
        Task("English review", due=today, task_id="b"),
        Task("Math tomorrow", due=date(2026, 9, 27), task_id="c"),
    ]
    controller = TaskPickerController(
        tasks,
        labeler=lambda task: task.summary,
        selected_date=today,
        today=today,
    )

    controller.search("math")
    assert controller.view().tasks.labels == ("Math review",)

    controller.search("")
    assert controller.view().tasks.labels == ("Math review", "English review")
