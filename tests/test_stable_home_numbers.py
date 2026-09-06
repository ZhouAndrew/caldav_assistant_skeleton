from caldav_assistant.internal.cli.smooth_home import _stable_home_items


def test_upcoming_remains_second_when_recommendation_appears():
    degraded = _stable_home_items(
        (
            "Choose a Task and start",
            "Upcoming — next 24h",
            "Today",
            "Stay in console",
        )
    )
    healthy = _stable_home_items(
        (
            "Start recommended Task — Homework",
            "Choose a Task and start",
            "Upcoming — next 24h",
            "Today",
            "Stay in console",
        )
    )

    assert degraded[:2] == (
        "Choose a Task and start",
        "Upcoming — next 24h",
    )
    assert healthy[:2] == (
        "Start recommended Task — Homework",
        "Upcoming — next 24h",
    )
    assert healthy[2] == "Choose a Task and start"


def test_upcoming_remains_second_while_current_work_is_active():
    items = _stable_home_items(
        (
            "Return to Waiting Mode — Homework",
            "Upcoming — next 24h",
            "Today",
            "Stay in console",
        )
    )

    assert items[:2] == (
        "Return to Waiting Mode — Homework",
        "Upcoming — next 24h",
    )
