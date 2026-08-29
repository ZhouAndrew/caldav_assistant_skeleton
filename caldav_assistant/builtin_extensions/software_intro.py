"""Default-on software introduction for the interactive CLI.

This is intentionally an extension rather than hard-coded REPL text.  It uses the
public Full Extension API hook and can be disabled through the normal extension
lifecycle with ``extension disable software_intro``.
"""
from __future__ import annotations

from caldav_assistant.api.v1.hooks import on


_EN = """Welcome to CalDAV Assistant.

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

_ZH_CN = """欢迎使用 CalDAV Assistant。

这是一个本地优先的 CalDAV 命令行助手。
  Task（任务）= 要完成的工作，可以 start / pause / resume / done。
  Event（事件）= 按时间发生的事项，不存在“完成”生命周期。

常用命令：
  today   查看今天
  next    查看建议的下一项
  start / pause / resume / done
  edit    修改 Task
  help    查看全部命令

Task / Event 的事实保存在 CalDAV；扩展通过同一个 Core 添加能力。

这段介绍来自默认启用的扩展：software_intro
不想每次进入交互式 CLI 都看到它：
  extension disable software_intro

以后想重新开启：
  extension enable software_intro"""


def _fallback_for(ctx) -> str:
    settings = getattr(ctx, "settings", None)
    getter = getattr(settings, "get", None)
    if callable(getter):
        try:
            locale = str(getter("ui.locale", "en") or "en")
        except Exception:
            locale = "en"
        if locale.casefold().startswith("zh"):
            return _ZH_CN
    return _EN


@on("cli.repl.started")
def introduce(ctx) -> None:
    """Show a short introduction after the interactive REPL banner."""
    fallback = _fallback_for(ctx)
    translate = getattr(ctx.ui, "t", None)
    if callable(translate):
        text = translate("extension.software_intro", default=fallback)
    else:
        text = fallback
    ctx.ui.show(text)
