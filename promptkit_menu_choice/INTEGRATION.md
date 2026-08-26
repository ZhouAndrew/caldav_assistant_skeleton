# PromptKit + Menu / Choice integration

This bundle completes the frozen PromptKit + Menu / Choice layer only.
It deliberately does **not** replace Task/Event services, CommandService, CLI actions,
REPL parsing, RuntimeDispatcher, TemporalParser, or bootstrap wiring.

## Replace

- `caldav_assistant/internal/prompts/menu.py`
- `caldav_assistant/internal/prompts/kit.py`
- `caldav_assistant/internal/prompts/__init__.py`

## Add tests

- `tests/test_menu.py`
- `tests/test_prompt_kit.py`

The existing composition root already has the correct shape and needs no edit:

```python
io = StdConsoleIO()
menu = Menu(io)
prompts = PromptKit(io, menu, temporal, tasks, events)
```

## Frozen behavior enforced

- All menu loops live in `Menu`, not business actions.
- Numeric selection returns the actual value.
- `0/back`, `q/cancel`, and `?/help` are uniform.
- Optional default selection, paging, search, and multi-select are reusable bricks.
- Invalid user input never escapes as an ordinary parsing crash.
- PromptKit delegates dates/times to the injected TemporalService.
- Date-only handling remains TemporalParser's responsibility; PromptKit never inserts midnight.
- `choose_task()` / `choose_event()` only query injected APIs; they do not mutate objects.
- `confirm_danger()` is intentionally stronger than normal yes/no confirmation.
- Existing Easy API shapes remain compatible: `ctx.ui.confirm(...)` and
  `ctx.ui.choose(..., multiple=True)` still work.

## Test

```bash
pytest -q tests/test_menu.py tests/test_prompt_kit.py
pytest -q
```
