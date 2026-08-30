from caldav_assistant.internal.cli.io import StdConsoleIO as LegacyStdConsoleIO
from caldav_assistant.internal.clients.terminal import StdConsoleIO
from caldav_assistant.internal.presentation import HtmlRenderer, JsonRenderer, TextRenderer
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
    assert text == "Edit <task>\n1. Due & date\n2. Title\nPage 1/2\n0. Back"

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
