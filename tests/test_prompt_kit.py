from datetime import date, datetime, time, timedelta

from caldav_assistant.internal.prompts import Menu, PromptKit


class FakeIO:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.output = []

    def read(self, prompt=""):
        self.output.append(prompt)
        return self.answers.pop(0)

    def write(self, text, end="\n"):
        self.output.append(str(text))


class FakeTemporal:
    def parse_date(self, text, *, bias="any"):
        if text == "bad":
            raise ValueError("bad date")
        assert bias in {"any", "future", "past"}
        return date(2026, 8, 30)

    def parse_datetime(self, text, *, bias="any"):
        if text == "bad":
            raise ValueError("bad datetime")
        return datetime(2026, 8, 30, 17, 0)

    def parse_time(self, text):
        if text == "bad":
            raise ValueError("bad time")
        return time(17, 0)


class ListAPI:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def list(self, **filters):
        self.calls.append(filters)
        return list(self.items)


class Item:
    def __init__(self, summary, *, due=None, start=None):
        self.summary = summary
        self.due = due
        self.start = start


def make(*answers, tasks=None, events=None):
    io = FakeIO(*answers)
    kit = PromptKit(io, Menu(io), FakeTemporal(), tasks, events)
    return kit, io


def test_text_and_yes_no_bad_input_do_not_crash():
    kit, io = make("", "hello", "maybe", "y")
    assert kit.ask_text("Name") == "hello"
    assert kit.ask_yes_no("Continue") is True
    assert any("cannot be empty" in line for line in io.output)
    assert any("Please answer" in line for line in io.output)


def test_temporal_prompts_reuse_temporal_service_and_retry():
    kit, io = make("bad", "August30", "bad", "17:00", "tomorrow 17:00")
    assert kit.ask_date("Due?", bias="future") == date(2026, 8, 30)
    assert kit.ask_time("Time?") == time(17, 0)
    assert kit.ask_datetime("When?") == datetime(2026, 8, 30, 17, 0)
    assert any("Could not understand" in line for line in io.output)


def test_duration_and_cancel():
    kit, _ = make("1h30m", "q")
    assert kit.ask_duration() == timedelta(minutes=90)
    assert kit.ask_text() is None


def test_choose_task_event_only_query_services():
    tasks = ListAPI([Item("Report", due=date(2026, 8, 30))])
    events = ListAPI([Item("Lesson", start=datetime(2026, 8, 30, 17, 0))])
    kit, _ = make("1", "1", tasks=tasks, events=events)

    assert kit.choose_task(category="school").summary == "Report"
    assert tasks.calls == [{"category": "school"}]
    assert kit.choose_event().summary == "Lesson"


def test_confirm_and_confirm_danger_are_distinct_bricks():
    kit, _ = make("y", "YES")
    assert kit.confirm("Complete?") is True
    assert kit.confirm_danger("Delete everything?") is True

    kit, _ = make("y")
    assert kit.confirm_danger("Delete everything?") is False
