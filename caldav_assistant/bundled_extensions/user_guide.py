"""Bundled interactive teaching extension for CalDAV Assistant.

This module intentionally uses only the public Easy / Full Extension APIs.  It is
read-only with respect to Task/Event facts: the guide explains mutating commands but
never completes, edits, starts, pauses, resumes, or deletes work on the user's behalf.
"""
from __future__ import annotations

from typing import Any

from caldav_assistant.api import ValidationError
from caldav_assistant.easy import choose, command, show


EXTENSION_NAME = "user_guide"
EXTENSION_VERSION = "1.0"


TOPICS: dict[str, tuple[str, str]] = {
    "quickstart": (
        "快速开始",
        """CalDAV Assistant 最常用的工作流：

1. `today` — 看今天相关的任务和事件。
2. `next` — 让程序给出下一件最值得处理的事。
3. `start` — 开始真正工作；不是修改计划开始时间。
4. `current` — 看现在正在做什么。
5. `pause` — 暂停当前工作。
6. `resume` — 继续之前暂停的工作。
7. `done` — 完成任务。
8. `edit` — 修改标题、截止日期、优先级等计划信息。

推荐第一次先只试：`today` → `next` → `help start`。
这些都是读取/帮助操作，不会改任务。""",
    ),
    "setup": (
        "第一次设置",
        """第一次使用建议按这个顺序：

1. 输入 `settings`。
2. 进入 `CalDAV`。
3. 设置 CalDAV server；如果发现了服务器，也可以选择发现结果。
4. 设置用户名和密码。
5. 选择 `Test connection`，确认能够看到 collection。
6. 进入 `Collection roles`，为 Task / Event / Work log 指定 collection。
7. 返回命令行，输入 `today` 做第一次读取验证。
8. 输入 `background enable` 开启正常的后台提醒。

诊断时也可以使用：
`settings caldav status`
`settings caldav test`
`settings caldav collections`

插件不会替你保存服务器地址或密码；这些必须经过正式 Settings 流程。""",
    ),
    "collections": (
        "Collections 怎么用",
        """Collection 可以理解为 CalDAV 服务器里的“数据容器”。

CalDAV Assistant 需要明确三个角色：

- Task collection：保存 VTODO，必须支持 `VTODO`。
- Event collection：保存普通日历事件，必须支持 `VEVENT`。
- Work log collection：保存真实工作时段，必须支持 `VEVENT`。

为什么要有 Work log？
`start / pause / resume / done` 描述的是“你实际什么时候工作”，不是任务计划字段。程序把这些工作区间记录成 CalDAV Work VEVENT，所以累计工作时间可以跨设备、可同步、可追溯。

设置方法：
`settings` → `CalDAV` → `Collection roles`

如果不知道选哪个，先看 `Collections`，注意每个 collection 后面的 `[VTODO]` / `[VEVENT]` 能力。""",
    ),
    "today": (
        "today 与编号",
        """`today` 用来查看今天相关的任务和事件。

在交互 CLI 中，显示列表后可以直接使用编号：

`start 1`
`done 2`
`edit 3`

编号指向“刚才显示的列表”，不是任务永久 ID。这样普通用户不需要复制 UID。

如果只是想知道下一步，不必自己在列表里判断，直接输入 `next`。""",
    ),
    "next": (
        "next 怎么用",
        """`next` 是“下一步建议”，不是自动替你执行任务。

典型流程：
`next`
→ 看建议
→ `start` 开始做推荐任务
→ `current` 随时确认当前工作
→ `pause` / `resume`
→ `done`

`next` 只负责排序和推荐；任务事实仍然来自 CalDAV。""",
    ),
    "work": (
        "start / pause / resume / done",
        """这四个命令描述的是人的真实工作过程：

`start [任务]`
开始现在实际工作。如果不写任务，程序会尝试使用推荐任务。

`current`
显示当前正在工作的任务。

`pause`
只暂停“当前正在做的任务”，所以不需要任务名。

`resume`
继续之前暂停的工作；如果有多个暂停任务，会让你选择。

`done [任务]`
把任务标记为完成。若当前正在工作，也会结束相应工作区间。

重要区别：任务的计划 DTSTART / due 属于 `edit`；真实开始、暂停、恢复属于工作记录。""",
    ),
    "edit": (
        "修改任务",
        """普通用户优先使用 `edit`：

`edit`
→ 选择任务
→ 选择要修改的字段
→ 输入新值

也可以在刚显示的列表后使用：`edit 2`。

目前常见字段包括标题、截止日期、优先级。

`edit-due` 是兼容命令；正常使用不需要记它。""",
    ),
    "background": (
        "后台与提醒",
        """后台 Assistant Service 负责同步、Reminder、系统通知和维护任务。

常用命令：
`background status` — 查看后台是否运行、后台提醒是否开启。
`background enable` — 开启正常的用户级后台提醒，并确保服务运行。
`background disable` — 关闭后台提醒并停止服务。
`background restart` — 排障或更新后重启后台。

普通用户不需要自己操作 systemd、launchctl 或 Windows 任务计划程序。""",
    ),
    "reminders": (
        "提醒是什么",
        """Reminder Engine 读取 Task/Event 事实并决定什么时候应该提醒，再交给 Notification Adapter 显示系统通知。

它不会把系统通知当成另一套任务数据库。

如果“没有提醒”，先检查：
1. `background status`
2. `settings caldav test`
3. `today` 是否能正常看到任务

后台停止或 CalDAV 配置错误时，先解决运行/连接问题。""",
    ),
    "undo": (
        "撤销",
        """程序为可撤销操作维护 Undo Journal。

如果刚刚做错了修改，可以使用：
`undo`

Undo 是恢复最近操作的辅助机制，不会把 Activity Journal 当作 Task 事实源。完成状态最终仍以 CalDAV 为准。""",
    ),
    "log": (
        "日志与 WordPress",
        """`log` 用于保存值得长期保留的文字记录：

`log 今天完成了第一版教学设计`

WordPress 是长期记录路径，不负责当前 Task 是否完成。

即使 WordPress 暂时不可用，任务完成本身也不应该因此失败；长期日志使用独立的 Outbox 路径。""",
    ),
    "extensions": (
        "扩展插件",
        """扩展使用统一 ExtensionManager 管理：

`extensions` — 列出扩展。
`extension add FILE` — 添加一个 Python 扩展。
`extension enable NAME`
`extension disable NAME`
`extension reload NAME`
`extension errors` — 查看扩展错误。

扩展命令进入同一个 CommandRegistry；插件不需要修改 Core 的命令 dispatcher。一个插件失败也不应该拖垮 Assistant。""",
    ),
    "debug": (
        "遇到问题怎么查",
        """建议按这个顺序排查，先看事实再重启：

1. `background status` — 后台是否运行？
2. `settings caldav status` — CalDAV 是否配置？
3. `settings caldav test` — 连接是否成功？
4. `settings caldav collections` — 能发现哪些 collection？
5. `today` — 读取链路是否正常？
6. `extension errors` — 是否有插件加载/Hook 错误？
7. 只有需要时再执行 `background restart`。

还可以输入 `help 命令名` 查看命令来源、别名和说明，例如：`help start`。""",
    ),
}


ALIASES = {
    "start": "work",
    "pause": "work",
    "resume": "work",
    "done": "work",
    "current": "work",
    "collection": "collections",
    "caldav": "setup",
    "settings": "setup",
    "reminder": "reminders",
    "notification": "reminders",
    "troubleshoot": "debug",
    "troubleshooting": "debug",
    "help": "quickstart",
    "wordpress": "log",
    "plugin": "extensions",
    "plugins": "extensions",
}


MENU = [
    ("快速开始", "quickstart"),
    ("第一次设置", "setup"),
    ("Collections 怎么用", "collections"),
    ("today / next", "today"),
    ("开始、暂停、恢复、完成", "work"),
    ("修改任务", "edit"),
    ("后台与提醒", "background"),
    ("撤销", "undo"),
    ("日志与 WordPress", "log"),
    ("扩展插件", "extensions"),
    ("遇到问题怎么查", "debug"),
]


def _normalize_topic(parts: tuple[Any, ...]) -> str:
    if not parts:
        return ""
    if not all(isinstance(part, str) for part in parts):
        raise ValidationError("guide topic must be text")
    topic = " ".join(part.strip() for part in parts if part.strip()).strip().casefold()
    topic = topic.replace("-", "_").replace(" ", "_")
    topic = ALIASES.get(topic, topic)
    return topic


def _topic_text(topic: str) -> str:
    if topic in {"topics", "list"}:
        lines = ["Guide topics:"]
        lines.extend(f"  {key:<12} {title}" for key, (title, _) in TOPICS.items())
        return "\n".join(lines)
    item = TOPICS.get(topic)
    if item is None:
        raise ValidationError(
            f"Unknown guide topic: {topic}. Use `guide topics` to list topics."
        )
    title, body = item
    return f"{title}\n{'=' * len(title)}\n{body}"


@command(
    "guide",
    aliases=("tutorial", "learn"),
    description="Interactive guide for learning CalDAV Assistant.",
)
def guide(*parts: Any):
    """Teach normal users how to operate CalDAV Assistant."""
    topic = _normalize_topic(parts)
    if topic:
        return _topic_text(topic)

    labels = [label for label, _ in MENU]
    topic_for_label = dict(MENU)

    while True:
        selected = choose(labels, title="CalDAV Assistant 使用向导")
        if selected is None:
            return None
        key = topic_for_label.get(str(selected))
        if key is None:
            raise ValidationError("Unknown guide menu selection")
        show(_topic_text(key))


__all__ = ["guide", "TOPICS", "EXTENSION_NAME", "EXTENSION_VERSION"]
