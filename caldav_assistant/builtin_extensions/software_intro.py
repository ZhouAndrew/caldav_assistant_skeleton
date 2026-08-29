"""Default-on software introduction for the interactive CLI.

This is intentionally an extension rather than hard-coded REPL text.  It uses the
public Full Extension API hook and can be disabled through the normal extension
lifecycle with ``extension disable software_intro``.
"""
from __future__ import annotations

from caldav_assistant.api.v1.hooks import on


_FALLBACK = """Welcome to CalDAV Assistant.

This is a local-first CalDAV command-line assistant.
  Task  = work you can start, pause, resume, and complete.
  Event = something scheduled to occur; Events are not completed.

Useful commands:
  today   show today's agenda
  next    show the suggested next item
  start / pause / resume / done
  edit    edit a Task
  help    show all commands

Task and Event facts stay in CalDAV. Extensions add features through the same Core.

This introduction comes from the default-enabled extension: software_intro
To stop showing it when the interactive CLI starts:
  extension disable software_intro

To turn it back on later:
  extension enable software_intro"""


@on("cli.repl.started")
def introduce(ctx) -> None:
    """Show a short introduction after the interactive REPL banner."""
    translate = getattr(ctx.ui, "t", None)
    if callable(translate):
        text = translate("extension.software_intro", default=_FALLBACK)
    else:
        text = _FALLBACK
    ctx.ui.show(text)
