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


def test_numeric_selection_returns_value_not_index():
    io = FakeIO("2")
    menu = Menu(io)
    assert menu.choose("Pick", [Choice("One", "a"), Choice("Two", "b")]) == "b"


def test_back_cancel_and_bad_input_are_recoverable():
    io = FakeIO("nonsense", "1")
    menu = Menu(io)
    assert menu.choose("Pick", ["A"]) == "A"
    assert any("Invalid choice" in line for line in io.output)

    assert Menu(FakeIO("0")).choose("Pick", ["A"]) is None
    assert Menu(FakeIO("q")).choose("Pick", ["A"]) is None


def test_default_multiple_search_and_paging():
    assert Menu(FakeIO("")).choose("Pick", ["A", "B"], default=2) == "B"
    assert Menu(FakeIO("1,3-4")).choose("Pick", [1, 2, 3, 4], multiple=True) == [1, 3, 4]
    assert Menu(FakeIO("/rep", "1")).choose("Pick", ["Email", "Report", "Plan"]) == "Report"
    assert Menu(FakeIO("n", "3")).choose("Pick", ["A", "B", "C"], page_size=2) == "C"


def test_help_does_not_leave_menu():
    io = FakeIO("?", "1")
    assert Menu(io).choose("Pick", ["A"]) == "A"
    assert any("q/cancel" in line for line in io.output)
