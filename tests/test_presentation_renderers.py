from caldav_assistant.internal.cli.io import StdConsoleIO as LegacyStdConsoleIO
from caldav_assistant.internal.clients.terminal import StdConsoleIO
from caldav_assistant.internal.presentation import HtmlRenderer, JsonRenderer, TextRenderer
from caldav_assistant.internal.presentation.renderers import _display_width
from caldav_assistant.internal.prompts import Choice, Menu


class FakeIO:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.output = []

    def read(self, prompt=""):
        self.output.append(prompt)
        return self.answers.pop(0)

    def write(self, text, end="\n"):
        self.output.append(str(text))


def test_terminal_client_boundary_keeps_legacy_import_and_pushback():
    assert LegacyStdConsoleIO is StdConsoleIO
    io = StdConsoleIO(input_fn=lambda prompt: "from-terminal")
    io.push_line("from-menu")
    assert io.read("> ") == "from-menu"
    assert io.read("> ") == "from-terminal"


def test_one_menu_view_renders_as_text_json_and_html():
    menu = Menu(FakeIO(), page_size=2)
    view = menu.presentation(
        "Edit <task>",
        [
            Choice("Due & date", object(), ("deadline",)),
            Choice("Title", object()),
            Choice("Priority", object()),
        ],
        page=1,
    )

    text = TextRenderer().render(view)
    assert text == (
        "Edit <task>\n"
        "1. Due & date\n"
        "2. Title\n"
        "Page 1/2\n"
        "n/next. Next page\n"
        "0. Back"
    )

    payload = JsonRenderer().render(view)
    assert payload["type"] == "menu"
    assert payload["title"] == "Edit <task>"
    assert payload["items"][0] == {
        "key": "1",
        "label": "Due & date",
        "keywords": ["deadline"],
        "disabled": False,
    }
    assert payload["page"] == {
        "number": 1,
        "count": 2,
        "query": "",
        "match_count": 3,
    }

    html = HtmlRenderer().render(view)
    assert 'data-view="menu"' in html
    assert 'data-choice-key="1"' in html
    assert "Edit &lt;task&gt;" in html
    assert "Due &amp; date" in html
    assert "<object object" not in html


def test_menu_public_presentation_preserves_filter_numbering_and_values():
    report = object()
    plan = object()
    menu = Menu(FakeIO(), page_size=1)
    view = menu.presentation(
        "Pick",
        [Choice("Email", object()), Choice("Report", report), Choice("Plan", plan)],
        query="p",
        page=2,
    )

    assert view.page == 2
    assert view.page_count == 2
    assert view.visible_match_count == 2
    assert [(item.key, item.label) for item in view.items] == [("2", "Plan")]
    assert view.resolve("2") is plan

    structured = menu.render_presentation(view, "json")
    html = menu.render_presentation(view, "html")
    assert structured["page"]["query"] == "p"
    assert 'data-choice-key="2"' in html


def test_interactive_menu_text_still_comes_from_the_same_view_model():
    io = FakeIO("2")
    menu = Menu(io)
    assert menu.choose("Pick", [Choice("One", "a"), Choice("Two", "b")]) == "b"
    assert io.output[:4] == ["Pick", "1. One", "2. Two", "0. Back"]


def test_terminal_text_renderer_packs_short_choices_horizontally_when_width_allows():
    menu = Menu(FakeIO())
    view = menu.presentation(
        "Many choices",
        ["One", "Two", "Three", "Four", "Five", "Six"],
        page_size=10,
    )

    rendered = TextRenderer(max_width=80).render(view)

    assert "1. One   2. Two" in rendered
    assert "3. Three" in rendered
    assert rendered.endswith("0. Back")


def test_real_terminal_adapter_owns_width_aware_menu_rendering():
    from io import StringIO

    output = StringIO()
    io = StdConsoleIO(
        input_fn=lambda _prompt: "4",
        stdout=output,
        terminal_width_fn=lambda: 80,
    )
    menu = Menu(io)

    assert menu.choose("Pick", ["One", "Two", "Three", "Four"]) == "Four"

    visible = output.getvalue()
    assert "1. One   2. Two" in visible
    assert "3. Three   4. Four" in visible


def test_horizontal_menu_orders_top_to_bottom_then_left_to_right():
    menu = Menu(FakeIO())
    view = menu.presentation(
        "Tasks",
        [f"Item {index}" for index in range(1, 11)],
        page_size=20,
    )

    # 50 columns is the narrowest width that enables the horizontal grid. With
    # these short labels it yields four columns and three rows.
    lines = TextRenderer(max_width=50).render_lines(view)
    choice_lines = [line for line in lines if ". " in line and not line.startswith("0.")]

    assert len(choice_lines) == 3

    # Column-major order: fill downward first, then continue in the next column.
    assert "1. Item 1" in choice_lines[0]
    assert "4. Item 4" in choice_lines[0]
    assert "7. Item 7" in choice_lines[0]
    assert "10. Item 10" in choice_lines[0]

    assert "2. Item 2" in choice_lines[1]
    assert "5. Item 5" in choice_lines[1]
    assert "8. Item 8" in choice_lines[1]

    assert "3. Item 3" in choice_lines[2]
    assert "6. Item 6" in choice_lines[2]
    assert "9. Item 9" in choice_lines[2]

    # Shared columns begin at exactly the same display-cell position on every row.
    starts_col2 = [
        _display_width(line[: line.index(f"{number}. ")])
        for line, number in zip(choice_lines, (4, 5, 6))
    ]
    starts_col3 = [
        _display_width(line[: line.index(f"{number}. ")])
        for line, number in zip(choice_lines, (7, 8, 9))
    ]
    assert len(set(starts_col2)) == 1
    assert len(set(starts_col3)) == 1
