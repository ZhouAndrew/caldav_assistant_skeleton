# 模块依赖 / 调用 / 输出总表

> 每个 Python 文件顶部还有更细的 `MODULE CONTRACT` 注释。

| 模块 | 允许导入 / 调用 | 对外提供 | 严禁 |
|---|---|---|---|
| `runtime` | bootstrap、IPC adapter、service lifecycle | `RuntimeClient`, `AssistantService` | 业务逻辑、直接改 Task |
| `cli` | `Remote*API Proxy`, `RuntimeClient`, `CommandService`, `PromptKit`, localization | `run_cli()` | 构造 TaskService/CalDAV client、CalDAV XML、SQLite 表、直接终端 OS/I/O API |
| `clients.terminal` | stdlib terminal/TTY APIs + presentation renderer | `StdConsoleIO` | Task/Event 业务、CalDAV、SQLite、IPC |
| `caldav.adapter` | 仅 domain types / stdlib；具体实现可导入第三方 CalDAV 库 | `CalDAVAdapter` | Task 业务规则 |
| `caldav.sync` | `CalDAVAdapter`, cache repository | `SyncEngine` | 直接给 CLI 输出 |
| `tasks` | `CalDAVAdapter`, Activity, Undo, Temporal types | `TaskService` | XML/HTTP、直接 SQLite |
| `events` | `CalDAVAdapter`, Activity, Undo | `EventService` | XML/HTTP、直接 SQLite |
| `agenda` | Task/Event query services + current state | `AgendaEngine`, `NextEngine`, `AgendaService` | 修改 CalDAV |
| `reminders` | Task/Event reads, storage state, NotificationService | `ReminderEngine`, `ReminderService` | OS 通知 API、另写 CalDAV client |
| `notifications` | `NotificationAdapter` | `NotificationService` | 业务 Task 状态 |
| `temporal` | stdlib + locale/config | `TemporalParser`, `TemporalService` | CLI input()/print() |
| `prompts` | TemporalService, Menu, localization, query services | `PromptKit`, `Menu` | 业务更新、XML、SQLite、print/input/getpass/stdin/stdout |
| `commands` | registry + service facade | `CommandRegistry`, `CommandService` | 巨大 if/elif dispatcher |
| `extensions` | CommandRegistry, hooks, API context | `ExtensionManager`, `HookRegistry` | 一个插件异常拖垮主程序 |
| `wordpress` | WordPressAdapter, OutboxRepository, Activity | `WordPressService` | 阻塞 Task complete 成功 |
| `activity` | ActivityRepository | `ActivityService` | 用 journal 覆盖 CalDAV 状态 |
| `storage` | sqlite3 / filesystem | repositories | 业务判断 |
| `localization` | locale resource provider | `LocaleService` | 散落硬编码 UI 文案 |
| `discovery` | discovery adapters/settings | `ServerDiscovery` | Task/Event 业务 |
| `settings` | storage repository + validators | `SettingsService` | 插件直接改配置文件 |
| `session` | local in-memory/session repo | `SessionService` | 成为 Task 事实源 |
| `undo` | undo repository + Service 回调句柄 | `UndoManager` | 各业务模块自行造 Undo 系统 |
| `intent` | IntentAdapter(s), domain request | `IntentParser` | 成为 Task Core |
| `easy` | 当前 `AssistantContext` 公共 API | Scratch-like functions | 暴露 IPC/XML/DB/async 复杂性 |
| `api.v1` | 稳定 contracts / context / errors / models | Public Object / Full API | 在 v1 内破坏性改名 |

## 典型调用链

### `edit due`

```text
CLI
 -> PromptKit.choose_task()
 -> PromptKit.ask_date()
 -> TemporalService.parse_date()
 -> TaskService.set_due()
 -> CalDAVAdapter.update()
 -> ActivityService.record()
 -> UndoManager.remember()
```

### Reminder

```text
AssistantService
 -> ReminderService.next_due()
 -> ReminderEngine.evaluate()
 -> NotificationService.send()
 -> NotificationAdapter.notify()
 -> Operating System
```

### WordPress log

```text
CLI / Easy API / Extension
 -> WordPressService.log()
 -> OutboxRepository.enqueue()
 -> WordPressAdapter.create_log()
 -> ActivityService.record()
```

失败时 Outbox 保留；Task/Event 操作不依赖 WordPress 成功。

### CLI 与后台

```text
CLI / Easy API / CLI Extension
 -> Remote*API Proxy
 -> RuntimeClient
 -> LocalIPCAdapter
 -> RuntimeDispatcher (explicit allow-list)
 -> SAME TaskService/EventService/etc. owned by background
```


## 前端 I/O 硬边界

所有人机交互先表达为通用交互积木，再由具体 Client Adapter 落地。业务、菜单和会话代码不得直接访问终端实现。

```text
Conversation / Navigation / CRUD
        -> PromptKit / Menu / Presentation
        -> Client IO
        -> Terminal Adapter
        -> stdin / stdout / readline / msvcrt / select / TTY control
```

Terminal Adapter 统一拥有：

- 普通输入输出：`read()`, `write()`, `error()`
- 隐藏输入：`ask_secret()`
- 菜单渲染：`render_menu()`
- 实时刷新：`update_line()`, `clear_line()`
- 终端提醒：`bell()`
- 非阻塞输入：`poll_input()`
- 交互控件按键翻译：`read_ui_action()`（方向键、PgUp/PgDn、Enter、Esc 等）
- 交互控件绘制：`render_scrollable_list()`, `render_date_picker()`, `render_task_picker()`；ANSI/raw-mode/msvcrt 只允许存在于 Terminal Adapter
- 终端能力检测：`display_width()`, `supports_readline_completion()`

`PromptKit` / `Menu` 提供类似常用对话框库的固定交互积木：`show`, `ask_text`, `ask_secret`, `ask_date`, `choose_date`, `ask_time`, `ask_datetime`, `ask_duration`, `ask_yes_no`, `confirm`, `confirm_danger`, `choose`, `choose_scrollable`, `choose_many`, `choose_task`, `choose_event`。`choose_task()` 是组合式 Task Picker：默认今天，以 Date Picker 过滤日期，以 Scrollable Selector 选择对应 Task；它们都是前端接口，不包含 Task 业务规则。

终端菜单由 Terminal Adapter 根据实际宽度布局：空间足够时使用对齐网格，编号顺序必须先从上到下、再从左到右；列宽按终端显示宽度（含中文双宽字符）统一对齐。窄终端、重定向输出或长项目自动减少列数，必要时退回单列。业务代码不得自行拼接列宽或 ANSI/CR 控制字符。


### 复用型选择控件

```text
PromptKit.choose_task()
        -> TaskPickerController
             -> DatePickerController / DateCursor
             -> ScrollCursor
        -> client-neutral TaskPickerView
        -> Terminal Adapter (or another future client)
```

Task Picker 默认定位“今天”，日期变动只改变界面过滤条件；Task 的 DUE/DTSTART、状态和 CalDAV 对象本身不会被修改。终端版控制约定为：`←/→` 前后一天，`PgUp/PgDn` 前后一个月，`↑/↓` 滚动当天 Task，`Enter` 选择，`i` 输入日期，`t` 回到今天，`/` 搜索，`q/Esc` 取消。Date Picker 和 Scrollable Selector 均可脱离 Task Picker 单独复用。
