"""Built-in English and Simplified-Chinese UI catalogs."""
from types import MappingProxyType

_EN = {
    "cli.banner": "CalDAV Assistant",
    "cli.hint": "Type 'help' for commands. Ctrl-D or Ctrl-C exits.",
    "cli.unknown_command": "Unknown command: {command}. Type 'help' for commands.",
    "cli.command_resolution": "Command → {command}",
    "cli.cancelled": "Cancelled.",
    "cli.invalid_input": "Invalid input: {error}",
    "cli.command_empty": "Command must not be empty.",
    "prompt.choose_task": "Choose task",
    "prompt.choose_event": "Choose event",
    "menu.back": "Back",
    "menu.cancel": "Cancel",
    "menu.help": "Help",
    "action.multiple_tasks": "Multiple tasks match: {query}",
    "action.complete": "Complete",
    "action.start": "Start",
    "action.pause": "Pause",
    "action.resume": "Resume",
    "action.edit": "Edit",
    "field.due": "Due date",
    "field.title": "Title",
    "field.priority": "Priority",
    "help.commands": "Commands:",
    "help.aliases": "aliases",
    "help.source": "source",
    "help.no_description": "No description.",
    "locale.language": "Language",
    "locale.choose": "Choose language",
    "locale.current": "Current language: {language}",
    "locale.changed": "Language changed to {language}.",
    "locale.english": "English",
    "locale.simplified_chinese": "Simplified Chinese",
    "command.today.description": "Show today's agenda.",
    "command.next.description": "Show the suggested next item.",
    "command.edit.description": "Interactively edit a Task using PromptKit bricks.",
    "command.done.description": "Complete a Task.",
    "command.start.description": "Start a Task.",
    "command.pause.description": "Pause a Task.",
    "command.resume.description": "Resume a Task.",
    "command.log.description": "Write a long-term log through WordPressService.",
    "command.help.description": "List commands or show command help.",
    "command.exit.description": "Leave the interactive REPL.",
    "command.edit-due.description": "Edit a Task due date.",
    "extension.none": "No extensions found. Run 'extension guide' to learn or 'extension new NAME' to create one.",
    "extension.list_title": "Extensions:",
    "extension.usage": "Usage: extension {guide|new|path|add|load|enable|disable|reload|unload|errors} ...\nRun 'extension guide' to learn how to add a feature with Python Easy API.",
    "extension.created": "Created Easy API extension {name} at {path} (disabled).\nEdit the file, then run: extension enable {name}",
    "extension.path": "Extension directory: {path}",
    "extension.guide": """Extensions add features with the Python Easy API.

Start here:
  from caldav_assistant.easy import *

The important model:
  Task  = work you can start, pause, resume, and complete.
  Event = something scheduled to occur. An Event is not completed.

Small example:
  from caldav_assistant.easy import command, show, overdue_tasks

  @command(\"urgent\")
  def urgent():
      show(overdue_tasks())

Create a starter file:
  extension new NAME

Then edit the generated Python file and enable it:
  extension enable NAME

After editing an enabled extension:
  extension reload NAME

If an extension fails:
  extension errors
  extension errors NAME

Useful Easy API bricks:
  tasks(), today_tasks(), overdue_tasks(), next_task(), choose_task()
  start(task), pause(task), resume(task), complete(task), set_due(task, when)
  events(), today_events(), next_event(), choose_event()
  add_event(), edit_event(), remove_event()
  today(), agenda(), next(), remind(), notify(), write_log(), command()

Use Task lifecycle actions only with Tasks. Agenda/today/next may contain both Tasks
and Events. Advanced extensions can use caldav_assistant.api / api.v1, but ordinary
extensions should prefer Easy API.""",
}

_ZH_CN = {
    "cli.banner": "CalDAV Assistant",
    "cli.hint": "输入 'help' 查看命令。Ctrl-D 或 Ctrl-C 退出。",
    "cli.unknown_command": "未知命令：{command}。输入 'help' 查看命令。",
    "cli.command_resolution": "命令 → {command}",
    "cli.cancelled": "已取消。",
    "cli.invalid_input": "输入无效：{error}",
    "cli.command_empty": "命令不能为空。",
    "prompt.choose_task": "选择任务",
    "prompt.choose_event": "选择事件",
    "menu.back": "返回",
    "menu.cancel": "取消",
    "menu.help": "帮助",
    "action.multiple_tasks": "多个任务匹配：{query}",
    "action.complete": "完成",
    "action.start": "开始",
    "action.pause": "暂停",
    "action.resume": "继续",
    "action.edit": "修改",
    "field.due": "截止日期",
    "field.title": "标题",
    "field.priority": "优先级",
    "help.commands": "命令：",
    "help.aliases": "别名",
    "help.source": "来源",
    "help.no_description": "无说明。",
    "locale.language": "语言",
    "locale.choose": "选择语言",
    "locale.current": "当前语言：{language}",
    "locale.changed": "语言已切换为 {language}。",
    "locale.english": "英语",
    "locale.simplified_chinese": "简体中文",
    "command.today.description": "显示今天的日程。",
    "command.next.description": "显示建议的下一项。",
    "command.edit.description": "使用 PromptKit 积木交互式修改任务。",
    "command.done.description": "完成一个任务。",
    "command.start.description": "开始一个任务。",
    "command.pause.description": "暂停一个任务。",
    "command.resume.description": "继续一个任务。",
    "command.log.description": "通过 WordPressService 写入长期日志。",
    "command.help.description": "列出命令或查看命令帮助。",
    "command.exit.description": "退出交互式命令行。",
    "command.edit-due.description": "修改一个任务的截止日期。",
    "extension.none": "还没有扩展。输入 'extension guide' 学习，或输入 'extension new NAME' 创建一个。",
    "extension.list_title": "扩展：",
    "extension.usage": "用法：extension {guide|new|path|add|load|enable|disable|reload|unload|errors} ...\n输入 'extension guide' 学习如何用 Python Easy API 添加功能。",
    "extension.created": "已创建 Easy API 扩展 {name}：{path}（尚未启用）。\n编辑文件后运行：extension enable {name}",
    "extension.path": "扩展目录：{path}",
    "extension.guide": """扩展功能以 Python Easy API 为第一入口。

从这里开始：
  from caldav_assistant.easy import *

先记住最重要的模型：
  Task（任务）= 要做的工作，可以 start / pause / resume / complete。
  Event（事件）= 在某个时间发生的事情；Event 不存在“完成”生命周期。

最小示例：
  from caldav_assistant.easy import command, show, overdue_tasks

  @command(\"urgent\")
  def urgent():
      show(overdue_tasks())

直接创建一个可编辑的模板：
  extension new NAME

编辑生成的 Python 文件，然后启用：
  extension enable NAME

修改已经启用的扩展后：
  extension reload NAME

扩展报错时：
  extension errors
  extension errors NAME

常用 Easy API 积木：
  tasks(), today_tasks(), overdue_tasks(), next_task(), choose_task()
  start(task), pause(task), resume(task), complete(task), set_due(task, when)
  events(), today_events(), next_event(), choose_event()
  add_event(), edit_event(), remove_event()
  today(), agenda(), next(), remind(), notify(), write_log(), command()

Task 生命周期操作只用于 Task；agenda / today / next 可以同时包含 Task 和 Event。
高级扩展可以使用 caldav_assistant.api / api.v1，但普通扩展应优先使用 Easy API。""",
}

BUILTIN_CATALOGS = MappingProxyType(
    {
        "en": MappingProxyType(_EN),
        "zh-CN": MappingProxyType(_ZH_CN),
    }
)
BUILTIN_LOCALE_METADATA = MappingProxyType(
    {
        "en": MappingProxyType(
            {"name": "English", "native_name": "English", "fallback": None}
        ),
        "zh-CN": MappingProxyType(
            {
                "name": "Simplified Chinese",
                "native_name": "简体中文",
                "fallback": "en",
            }
        ),
    }
)

__all__ = ["BUILTIN_CATALOGS", "BUILTIN_LOCALE_METADATA"]
