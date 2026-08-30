"""Default-on first-run/setup introduction for the interactive CLI.

The introduction is intentionally task-oriented rather than command-oriented. A new
user should be able to operate the program by pressing Enter and choosing numbers;
direct commands are optional shortcuts for experienced users.
"""
from __future__ import annotations

from caldav_assistant.api.v1.hooks import on


_EN_READY = """You do not need to learn CalDAV Assistant before using it.

At the `>` prompt:
  • press Enter to open the guided menu;
  • choose with numbers;
  • use 0 to go back one level.

Start from what you want to do: Agenda, Work, Logs, Manage, or Settings & setup.
Commands are optional shortcuts, not required knowledge. For example, experienced
users may use `add` or `edit-event` directly, but beginners never need to memorize them."""

_ZH_CN_READY = """使用 CalDAV Assistant 不需要先学习一套命令。

在 `>` 提示符处：
  • 直接按 Enter 打开引导菜单；
  • 用数字选择；
  • 输入 0 只返回上一层。

从你要做的事情开始选：日程、工作、日志、管理，或设置。
命令只是熟练后的快捷方式，不是使用前提；例如熟练后可以直接用 `add`、
`edit-event`，但新用户完全不需要先记住它们。"""

_EN_SETUP_SERVER = """First-run setup is not complete yet: CalDAV is not configured.
You can finish setup without learning commands.

At the `>` prompt press Enter, choose `Settings & setup`, then open the CalDAV settings.
The setup flow will guide you through server address/discovery, credentials when
needed, connection testing, and Collection roles for Tasks and Events.

Use numbers and 0/back. After setup, press Enter again and choose what you want to do."""

_ZH_CN_SETUP_SERVER = """首次设置还没有完成：CalDAV 尚未配置，但不需要先学命令。

在 `>` 提示符直接按 Enter，选择“Settings & setup / 设置”，再进入 CalDAV settings。
设置流程会依次引导：服务器地址或自动发现、需要时的账号凭据、连接测试，以及
Task / Event 的 Collection roles。

全程可以只用数字和 0 返回。设置完成后，再按 Enter 按目标选择功能即可。"""

_EN_SETUP_ROLES = """The CalDAV server is configured, but Task/Event Collection roles are not selected yet.

Press Enter → Settings & setup → CalDAV → Collection roles.
Choose a VTODO collection for Tasks and/or a VEVENT collection for Events.
The Work-log collection is optional.

You do not need to memorize these names for normal use; this is only the one-time
storage setup. The menu will guide normal use afterwards."""

_ZH_CN_SETUP_ROLES = """CalDAV 服务器已经配置，但还没有选好 Task / Event 的 Collection roles。

按 Enter → Settings & setup / 设置 → CalDAV → Collection roles。
为 Task 选择支持 VTODO 的 collection，并/或为 Event 选择支持 VEVENT 的 collection。
Work log collection 是可选项。

这些术语只用于一次性的存储配置，日常使用不需要记住；之后直接通过菜单按目标操作。"""


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
        # service is temporarily unavailable. Ordinary commands surface the actual
        # runtime failure when invoked.
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
    """Show a short next action, never a command vocabulary lesson."""
    ctx.ui.show(_fallback_for(ctx))
