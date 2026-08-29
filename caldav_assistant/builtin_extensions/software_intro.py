"""Default-on first-run/setup introduction for the interactive CLI.

This remains an extension rather than hard-coded REPL text.  It uses only the public
context/settings/UI surface and can be disabled through the normal extension
lifecycle with ``extension disable software_intro``.
"""
from __future__ import annotations

from caldav_assistant.api.v1.hooks import on


_EN_READY = """Welcome to CalDAV Assistant.

This is a local-first CalDAV command-line assistant.
  Task  = work you can start, pause, resume, and complete.
  Event = something scheduled to occur; Events are not completed.

Useful commands:
  today / next                 agenda and recommendation
  add                          create a Task or Event
  tasks / events               list CalDAV objects
  start / pause / resume / done
  edit / edit-event            modify Task or Event
  remove                       delete Task or Event with confirmation
  settings                     configuration
  help                         show all commands

Task and Event facts stay in CalDAV. Work-history VEVENTs are optional; without one,
Task lifecycle tracking falls back to the local Activity Journal.

This introduction comes from the default-enabled extension: software_intro
To stop showing it when the interactive CLI starts:
  extension disable software_intro

To turn it back on later:
  extension enable software_intro"""

_ZH_CN_READY = """欢迎使用 CalDAV Assistant。

这是一个本地优先的 CalDAV 命令行助手。
  Task（任务）= 要完成的工作，可以 start / pause / resume / done。
  Event（事件）= 按时间发生的事项，不存在“完成”生命周期。

常用命令：
  today / next                 查看今天与下一项
  add                          新建 Task 或 Event
  tasks / events               列出 Task / Event
  start / pause / resume / done
  edit / edit-event            修改 Task / Event
  remove                       确认后删除 Task / Event
  settings                     设置
  help                         查看全部命令

Task / Event 的事实保存在 CalDAV。Work history Calendar 是可选增强；如果没有设置，
Task 生命周期仍可使用，并会退回本地 Activity Journal 记录。

这段介绍来自默认启用的扩展：software_intro
不想每次进入交互式 CLI 都看到它：
  extension disable software_intro

以后想重新开启：
  extension enable software_intro"""

_EN_SETUP_SERVER = """Welcome to CalDAV Assistant.

First-run setup is not complete yet: no CalDAV server is configured.

Start here:
  settings

Then open CalDAV and do these in order:
  1. Set CalDAV server (or use a discovered server)
  2. Configure credentials if your server requires them
  3. Test connection
  4. Open Collection roles and choose the Task/Event collections you want to use

After that, try:
  add
  today
  next

You can disable this startup guide later with:
  extension disable software_intro"""

_ZH_CN_SETUP_SERVER = """欢迎使用 CalDAV Assistant。

首次设置还没有完成：目前没有配置 CalDAV 服务器。

先输入：
  settings

进入 CalDAV 后按顺序完成：
  1. 设置 CalDAV server（或使用自动发现的服务器）
  2. 如果服务器需要认证，设置 credentials
  3. Test connection
  4. 打开 Collection roles，选择要使用的 Task / Event collection

完成后可以先试：
  add
  today
  next

以后不想每次启动都看到这段引导，可以输入：
  extension disable software_intro"""

_EN_SETUP_ROLES = """CalDAV server configuration exists, but Task/Event collection roles are still empty.

Finish setup with:
  settings
  → CalDAV
  → Test connection
  → Collection roles

Choose a VTODO collection for Tasks and/or a VEVENT collection for Events.
The Work log collection is optional: start/pause/resume still work without it and
fall back to the Activity Journal.

Then try `add`, `today`, or `next`."""

_ZH_CN_SETUP_ROLES = """已经有 CalDAV server 配置，但 Task / Event 的 collection roles 还没有设置。

请继续：
  settings
  → CalDAV
  → Test connection
  → Collection roles

为 Task 选择支持 VTODO 的 collection，并/或为 Event 选择支持 VEVENT 的 collection。
Work log collection 是可选项：即使不设置，start / pause / resume 仍然可以使用，
只是会退回 Activity Journal 记录。

完成后可以试 `add`、`today` 或 `next`。"""


def _locale(ctx) -> str:
    settings = getattr(ctx, "settings", None)
    getter = getattr(settings, "get", None)
    if callable(getter):
        try:
            return str(getter("ui.locale", "en") or "en")
        except Exception:
            pass
    return "en"


def _setup_stage(ctx) -> str:
    settings = getattr(ctx, "settings", None)
    getter = getattr(settings, "get", None)
    if not callable(getter):
        return "ready"
    try:
        base_url = getter("caldav.base_url", None)
        task_role = getter("caldav.task_collection_url", None)
        event_role = getter("caldav.event_collection_url", None)
    except Exception:
        # Startup guidance must never make the CLI unusable when the background
        # service is temporarily unavailable.  Ordinary commands will surface the
        # real runtime error when the user invokes them.
        return "ready"
    if not base_url:
        return "server"
    if not task_role and not event_role:
        return "roles"
    return "ready"


def _fallback_for(ctx) -> str:
    zh = _locale(ctx).casefold().startswith("zh")
    stage = _setup_stage(ctx)
    if stage == "server":
        return _ZH_CN_SETUP_SERVER if zh else _EN_SETUP_SERVER
    if stage == "roles":
        return _ZH_CN_SETUP_ROLES if zh else _EN_SETUP_ROLES
    return _ZH_CN_READY if zh else _EN_READY


@on("cli.repl.started")
def introduce(ctx) -> None:
    """Show setup guidance on first run, otherwise the concise usage introduction."""
    # The content is dynamic, so it deliberately uses the public UI directly rather
    # than one static catalog key whose text could not reflect setup stage.
    ctx.ui.show(_fallback_for(ctx))
