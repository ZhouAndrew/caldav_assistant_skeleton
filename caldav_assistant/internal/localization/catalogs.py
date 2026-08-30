"""Built-in English and Simplified-Chinese UI catalogs."""
from types import MappingProxyType

_EN = {
    "cli.banner": "CalDAV Assistant",
    "cli.hint": "Press Enter for the guided menu. Commands are optional shortcuts. Ctrl-D or Ctrl-C exits.",
    "cli.unknown_command": "Unknown command: {command}. Type 'help' for commands.",
    "cli.unsupported_command": "Unsupported command: {command}. Type 'help' for available commands.",
    "cli.command_supported_extension_missing": "Command '{command}' is supported by official extension '{extension}', but that extension is not installed in this build.",
    "cli.command_supported_extension_disabled": "Command '{command}' is supported, but extension '{extension}' is disabled. Enable it with: extension enable {extension}",
    "cli.command_supported_extension_error": "Command '{command}' is supported by extension '{extension}', but the extension failed to load. Check: extension errors {extension}",
    "cli.command_supported_extension_unavailable": "Command '{command}' is supported by extension '{extension}', but is not available right now. Try: extension reload {extension}",
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
    "extension.official_title": "Official bundled extensions:",
    "extension.user_title": "User extensions:",
    "extension.none_official": "none",
    "extension.none_user": "none",
    "extension.origin.official": "official",
    "extension.origin.user": "user",
    "extension.origin.official_long": "Official (bundled with CalDAV Assistant)",
    "extension.origin.user_long": "User extension",
    "extension.list_hint": "Manage with: extension info NAME | enable/disable/reload NAME",
    "extension.official_hint": "Official source code is shipped with the app. You can enable, disable, reload, inspect errors, or reset an official extension to its default state.",
    "extension.official_source_note": "Official source is managed by application updates; manage its lifecycle with enable/disable/reload/reset instead of editing the bundled file.",
    "extension.user_source_note": "User source is yours to edit. Run `extension dev` for VS Code/Pylance setup.",
    "extension.reset_done": "Reset official extension to packaged default → {record}",
    "extension.dev_created": "created",
    "extension.dev_existing": "already existed; left unchanged",
    "extension.dev": "VS Code extension workspace: {root}\nPylance settings: {settings} ({state})\nOpen that directory in VS Code, then select the Python interpreter where caldav-assistant is installed. The package ships py.typed + Easy API stubs for autocomplete and type checking.",
    "extension.usage": "Usage: extension {guide|new|dev|path|official|user|info|reset|add|load|enable|disable|reload|unload|errors} ...\nRun 'extension guide' for Easy API and VS Code development help.",
    "extension.created": "Created typed Easy API extension {name} at {path} (disabled).\nFor VS Code support run: extension dev\nThen enable it with: extension enable {name}",
    "extension.path": "Extension directory: {path}",
    "extension.guide": """Extensions add features with the Python Easy API.

Start here:
  from caldav_assistant.easy import command, show, overdue_tasks

The important model:
  Task  = work you can start, pause, resume, and complete.
  Event = something scheduled to occur. An Event is not completed.

Small example:
  @command(\"urgent\")
  def urgent() -> None:
      show(overdue_tasks())

Create a starter file:
  extension new NAME

Prepare the extension directory for VS Code/Pylance:
  extension dev

The installed package includes PEP 561 typing, an Easy API stub, and typed Object API
Protocols. Select the Python interpreter where caldav-assistant is installed and VS
Code can autocomplete imports, show signatures, and type-check Task/Event usage.

Official bundled extensions:
  extension official
  extension info NAME
  extension enable|disable NAME
  extension reset NAME

After editing an enabled user extension:
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
    "cli.hint": "直接按 Enter 打开引导菜单；命令只是可选快捷方式。Ctrl-D 或 Ctrl-C 退出。",
    "cli.unknown_command": "未知命令：{command}。输入 'help' 查看命令。",
    "cli.unsupported_command": "不支持的命令：{command}。输入 'help' 查看当前可用命令。",
    "cli.command_supported_extension_missing": "命令“{command}”受官方扩展“{extension}”支持，但当前软件包中没有安装该扩展。",
    "cli.command_supported_extension_disabled": "命令“{command}”受支持，但扩展“{extension}”当前已禁用。启用：extension enable {extension}",
    "cli.command_supported_extension_error": "命令“{command}”受扩展“{extension}”支持，但扩展加载失败。检查：extension errors {extension}",
    "cli.command_supported_extension_unavailable": "命令“{command}”受扩展“{extension}”支持，但当前不可用。可尝试：extension reload {extension}",
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
    "extension.official_title": "官方内置扩展：",
    "extension.user_title": "用户扩展：",
    "extension.none_official": "无",
    "extension.none_user": "无",
    "extension.origin.official": "官方",
    "extension.origin.user": "用户",
    "extension.origin.official_long": "官方扩展（随 CalDAV Assistant 提供）",
    "extension.origin.user_long": "用户扩展",
    "extension.list_hint": "管理：extension info NAME | enable/disable/reload NAME",
    "extension.official_hint": "官方源码随软件提供。用户可以启用、禁用、重新加载、查看错误，或恢复官方默认启用状态。",
    "extension.official_source_note": "官方源码由软件更新管理；请使用 enable/disable/reload/reset 管理生命周期，不要直接修改内置文件。",
    "extension.user_source_note": "用户扩展源码由你管理。输入 `extension dev` 可准备 VS Code/Pylance 开发环境。",
    "extension.reset_done": "已恢复官方扩展的出厂默认状态 → {record}",
    "extension.dev_created": "已创建",
    "extension.dev_existing": "已存在，未覆盖",
    "extension.dev": "VS Code 扩展工作区：{root}\nPylance 设置：{settings}（{state}）\n用 VS Code 打开这个目录，然后选择安装了 caldav-assistant 的 Python 解释器。安装包自带 py.typed 和 Easy API 类型 stub，可用于自动补全和类型检查。",
    "extension.usage": "用法：extension {guide|new|dev|path|official|user|info|reset|add|load|enable|disable|reload|unload|errors} ...\n输入 'extension guide' 查看 Easy API 与 VS Code 开发说明。",
    "extension.created": "已创建带类型提示的 Easy API 扩展 {name}：{path}（尚未启用）。\nVS Code 支持：extension dev\n然后启用：extension enable {name}",
    "extension.path": "扩展目录：{path}",
    "extension.guide": """扩展功能以 Python Easy API 为第一入口。

推荐从明确导入开始：
  from caldav_assistant.easy import command, show, overdue_tasks

先记住最重要的模型：
  Task（任务）= 要做的工作，可以 start / pause / resume / complete。
  Event（事件）= 在某个时间发生的事情；Event 不存在“完成”生命周期。

最小示例：
  @command(\"urgent\")
  def urgent() -> None:
      show(overdue_tasks())

创建一个可编辑模板：
  extension new NAME

准备 VS Code / Pylance 开发环境：
  extension dev

安装包自带 PEP 561 的 py.typed、Easy API 类型 stub 和 Object API Protocol。
在 VS Code 中选择安装了 caldav-assistant 的 Python 解释器后，可以获得导入补全、
函数签名、返回类型，以及 Task / Event 的类型检查。

管理官方内置扩展：
  extension official
  extension info NAME
  extension enable|disable NAME
  extension reset NAME

修改已经启用的用户扩展后：
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
