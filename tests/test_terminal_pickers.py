from datetime import date
from io import StringIO

from caldav_assistant.internal.clients.terminal import StdConsoleIO
from caldav_assistant.internal.presentation import (
    DatePickerView,
    ScrollableListView,
    TaskPickerView,
)


def test_injected_ui_key_actions_are_returned_without_terminal_parsing():
    actions = iter(["down", "enter"])
    console = StdConsoleIO(
        stdout=StringIO(),
        ui_key_fn=lambda: next(actions),
    )

    assert console.supports_interactive_picker() is True
    assert console.read_ui_action() == "down"
    assert console.read_ui_action() == "enter"


def test_date_picker_renderer_marks_selected_today_and_content_dates():
    output = StringIO()
    console = StdConsoleIO(
        stdout=output,
        terminal_width_fn=lambda: 100,
    )
    weeks = (
        (
            date(2026, 9, 21),
            date(2026, 9, 22),
            date(2026, 9, 23),
            date(2026, 9, 24),
            date(2026, 9, 25),
            date(2026, 9, 26),
            date(2026, 9, 27),
        ),
    )
    view = DatePickerView(
        title="Choose date",
        selected=date(2026, 9, 26),
        today=date(2026, 9, 25),
        month_label="September 2026",
        weeks=weeks,
        marked_dates=(date(2026, 9, 24), date(2026, 9, 26)),
    )

    console.render_date_picker(view)

    text = output.getvalue()
    assert "< September 2026 >" in text
    assert "24•" in text
    assert "*25" in text
    assert "[26]" in text
    assert "PgUp/PgDn month" in text


def test_task_picker_renderer_combines_calendar_and_scrollable_task_list():
    output = StringIO()
    console = StdConsoleIO(
        stdout=output,
        terminal_width_fn=lambda: 100,
    )
    weeks = (
        (
            date(2026, 9, 21),
            date(2026, 9, 22),
            date(2026, 9, 23),
            date(2026, 9, 24),
            date(2026, 9, 25),
            date(2026, 9, 26),
            date(2026, 9, 27),
        ),
    )
    calendar = DatePickerView(
        title="Calendar",
        selected=date(2026, 9, 26),
        today=date(2026, 9, 26),
        month_label="September 2026",
        weeks=weeks,
        marked_dates=(date(2026, 9, 26),),
    )
    tasks = ScrollableListView(
        title="Tasks · 2026-09-26 · 3",
        labels=("Anki", "Chemistry", "Chinese dictation"),
        selected_index=1,
        offset=0,
        page_size=8,
    )
    view = TaskPickerView(
        title="Choose a Task to work on",
        calendar=calendar,
        tasks=tasks,
        footer="controls",
    )

    console.render_task_picker(view)

    text = output.getvalue()
    assert "Choose a Task to work on" in text
    assert "[26]" in text
    assert "  1. Anki" in text
    assert ">  2. Chemistry" in text
    assert "  3. Chinese dictation" in text
    assert text.rstrip().endswith("controls")


def test_scrollable_renderer_only_marks_current_selection():
    output = StringIO()
    console = StdConsoleIO(
        stdout=output,
        terminal_width_fn=lambda: 80,
    )
    view = ScrollableListView(
        title="Pick",
        labels=("A", "B", "C", "D"),
        selected_index=2,
        offset=1,
        page_size=2,
    )

    console.render_scrollable_list(view, footer="↑/↓ move")

    text = output.getvalue()
    assert "  2. B" in text
    assert ">  3. C" in text
    assert "A" not in text
    assert "D" not in text
