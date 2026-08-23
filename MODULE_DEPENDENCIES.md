# 模块依赖 / 调用 / 输出总表

> 每个 Python 文件顶部还有更细的 `MODULE CONTRACT` 注释。

| 模块 | 允许导入 / 调用 | 对外提供 | 严禁 |
|---|---|---|---|
| `runtime` | bootstrap、IPC adapter、service lifecycle | `RuntimeClient`, `AssistantService` | 业务逻辑、直接改 Task |
| `cli` | `Remote*API Proxy`, `RuntimeClient`, `CommandService`, `PromptKit`, localization | `run_cli()` | 构造 TaskService/CalDAV client、CalDAV XML、SQLite 表、OS API |
| `caldav.adapter` | 仅 domain types / stdlib；具体实现可导入第三方 CalDAV 库 | `CalDAVAdapter` | Task 业务规则 |
| `caldav.sync` | `CalDAVAdapter`, cache repository | `SyncEngine` | 直接给 CLI 输出 |
| `tasks` | `CalDAVAdapter`, Activity, Undo, Temporal types | `TaskService` | XML/HTTP、直接 SQLite |
| `events` | `CalDAVAdapter`, Activity, Undo | `EventService` | XML/HTTP、直接 SQLite |
| `agenda` | Task/Event query services + current state | `AgendaEngine`, `NextEngine`, `AgendaService` | 修改 CalDAV |
| `reminders` | Task/Event reads, storage state, NotificationService | `ReminderEngine`, `ReminderService` | OS 通知 API、另写 CalDAV client |
| `notifications` | `NotificationAdapter` | `NotificationService` | 业务 Task 状态 |
| `temporal` | stdlib + locale/config | `TemporalParser`, `TemporalService` | CLI input()/print() |
| `prompts` | TemporalService, Menu, localization, query services | `PromptKit`, `Menu` | 业务更新、XML、SQLite |
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
