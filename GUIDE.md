# CalDAV Assistant — User + Developer Guide / 使用与开发指南

> 这份 Guide 不再把功能名重复一遍当作“说明”。它回答三个具体问题：
>
> 1. **一个第一次打开软件的人，下一步按什么？**
> 2. **为什么菜单现在真的有父层、子层和返回路径？**
> 3. **开发者增加功能时，该改哪一层，绝对不该把什么逻辑塞进菜单？**

CalDAV Assistant v1 的冻结原则仍然不变：CLI-first；CalDAV 保存 Task/Event 事实；SQLite 只保存缓存与 Assistant 辅助状态；WordPress 保存长期文字记录；Menu/Prompt/Temporal/Core Service/Adapter 分层；Easy API 保持 Scratch-like。实现不得为了技术方便反过来提高用户学习成本。

---

# 一、第一次使用：不用学命令

启动：

```bash
caldav-assistant
```

看到 `>` 后，**直接按 Enter**。

```text
CalDAV Assistant
Press Enter for the guided menu. Commands are optional shortcuts.

>
```

Enter 会打开：

```text
CalDAV Assistant

1. Agenda
2. Work
3. Logs
4. Manage
5. Settings & setup
6. Help
0. Leave menu
```

最低学习成本只有：

```text
数字     选择
0        返回上一层
?        当前菜单帮助
```

`today`、`next`、`add`、`done` 等仍然存在，但它们是熟练用户的快捷方式，不是普通用户开始使用前必须背下来的词汇。

## 按目标操作

### 看今天

```text
Enter → Agenda → Today
```

### 看下一步建议

```text
Enter → Agenda → Next
```

### 开始 / 暂停 / 继续 / 完成工作

```text
Enter → Work
```

然后按目标选择。

### 新建 Task 或 Event

```text
Enter → Manage → Add Task/Event
```

### 修改 Task

```text
Enter → Manage → Tasks → Edit Task
```

### 修改 Event

```text
Enter → Manage → Events → Edit Event
```

### 设置

```text
Enter → Settings & setup
```

### 看历史或 WordPress 日志

```text
Enter → Logs
```

---

# 二、Task 与 Event：用户真正需要知道的模型

## Task

Task 是“要完成的工作”，底层是 CalDAV `VTODO`。

例如：

```text
写报告
背单词
修电脑
```

Task 有工作生命周期：

```text
start → pause → resume → complete
```

## Event

Event 是“某个时间发生的事情”，底层是 CalDAV `VEVENT`。

例如：

```text
14:30 开会
20:00 Cambly
```

Event 可以查看、编辑、删除，但没有 Task 那种 `done` 生命周期。

这一区分来自数据模型，不是 UI 随便分的两个菜单。

---

# 三、第一次 CalDAV 设置

如果服务器还没配置，启动说明只告诉你下一步，不再先发一张命令表。

```text
Enter
→ Settings & setup
→ CalDAV
```

随后按设置菜单完成：

1. Server 地址或自动发现；
2. 需要时输入 credentials；
3. Test connection；
4. Collection roles；
5. Task 选择支持 `VTODO` 的 collection；
6. Event 选择支持 `VEVENT` 的 collection（需要 Event 时）。

Work-log collection 是可选增强。没有它，Task 的 start/pause/resume 仍然工作，活动过程可以退回本地 Activity Journal。

`VTODO / VEVENT / collection role` 属于一次性存储配置知识，不应该成为日常使用前提。

---

# 四、多级菜单现在为什么是真的“有层”

当前导航结构：

```text
CalDAV Assistant
├─ Agenda
│  ├─ Today
│  ├─ Next
│  └─ Current work
├─ Work
│  ├─ Start recommended task
│  ├─ Pause current task
│  ├─ Resume paused task
│  └─ Complete task
├─ Logs
│  ├─ Write log
│  ├─ Activity today
│  ├─ Task history
│  ├─ WordPress today (real post)
│  └─ Pending WordPress uploads
├─ Manage
│  ├─ Add Task/Event
│  ├─ Tasks
│  │  ├─ List Tasks
│  │  ├─ Edit Task
│  │  └─ Complete Task
│  ├─ Events
│  │  ├─ List Events
│  │  └─ Edit Event
│  └─ Remove Task/Event
├─ Settings & setup
└─ Help
```

进入第三层时标题显示当前位置：

```text
CalDAV Assistant > Manage > Tasks
```

并显示：

```text
0. Back to Manage
```

此时按 `0`，只回到 Manage；再按 `0`，才回 Root。

这不是仅仅换了标题，因为实现层维护一个真正的 navigation stack。

---

# 五、旧实现的问题到底是什么

旧代码虽然存在 `_agenda_menu()`、`_work_menu()`、`_manage_menu()` 等函数，但实际运行更接近：

```text
Root chooser
↓
调用一个 submenu 函数
↓
submenu chooser
↓
执行一次 command
↓
整个函数返回
```

这里没有：

```text
parent node
navigation stack
current path
pop one level
```

所以它只是“连续调用两个 chooser”，不是一个真正的层级导航模型。

现在的结构是显式节点：

```python
NavigationMenu(
    "Manage",
    (
        NavigationCommand("Add Task/Event", "add"),
        NavigationMenu(
            "Tasks",
            (
                NavigationCommand("List Tasks", "tasks"),
                NavigationCommand("Edit Task", "edit"),
                NavigationCommand("Complete Task", "done"),
            ),
        ),
    ),
)
```

运行时：

```python
stack = [root]
```

进入 Manage：

```python
[root, manage]
```

进入 Tasks：

```python
[root, manage, tasks]
```

按 `0`：

```python
stack.pop()
```

得到：

```python
[root, manage]
```

因此“返回上一层”现在是数据结构上的事实。

Breadcrumb：

```text
CalDAV Assistant > Manage > Tasks
```

由 stack 动态生成，不是写死文案。

---

# 六、菜单不拥有 Task/Event 业务逻辑

这是开发边界。

一个菜单叶子只描述：

```text
显示 label
canonical command
可选参数
```

例如：

```python
NavigationCommand("Complete Task", "done")
```

执行路径：

```text
Navigation leaf
↓
ctx.commands.run("done")
↓
CommandService
↓
原有 done CLI composition
↓
TaskService.complete(...)
↓
CalDAVAdapter
↓
CalDAV VTODO
```

禁止在 navigation 里：

```python
task.status = "COMPLETED"
adapter.update_task(...)
```

也禁止复制 `done` 已经拥有的 Task 查找、确认、Undo、Activity 等流程。

**Navigation 决定“去哪里”；Core Service 决定“动作怎么做”。**

---

# 七、为什么 Navigation 现在复用统一 Menu

旧 Navigation 为了允许“菜单中直接输入正常命令”，自己写了一套 input loop：

```text
print title
print 1/2/3
read input
parse number
parse back
parse help
```

这与冻结的 `Menu / Choice` 模块重复，也会造成 Terminal 与未来 Web 客户端逐渐行为分叉。

现在选择行为回到：

```text
PromptKit.choose(...)
↓
Menu.choose(...)
↓
MenuView
↓
Text / JSON / HTML renderer
```

Terminal Navigation 唯一的额外需求是：

> 菜单里输入 `today` 时，不把它当“非法菜单选项”，而是交回正常 REPL。

因此共享 Menu 提供一个客户端组合 hook：

```python
Menu.choose(..., on_unmatched=callback)
```

Menu 自己仍然**不理解 command**。

终端 callback 只做：

```text
push_line(raw)
```

然后 Navigation 退出。

下一轮 REPL 才真正：

```text
parse_command_line
↓
CommandService
```

所以菜单没有变成第二个命令解释器。

---

# 八、为什么执行一个叶子后回到 `>`

例如：

```text
Enter → Agenda → Today
```

找到 `Today` 后：

```text
NavigationCommand("Today", "today")
↓
CommandService.run("today")
```

结果交给正常 CLI renderer 显示，然后返回 `>`。

这是刻意的：层级菜单负责**找到动作**，正常 REPL 负责**执行与渲染动作**。

如果选择叶子后仍长期卡在一个特殊菜单 event loop，就会形成第二套 CLI 生命周期和第二套输出规则。

因此：

- 进入子菜单、`0` 返回时，navigation stack 保持层级；
- 真正执行叶子动作以后，导航结束；
- 需要继续菜单时按 Enter 再打开。

这两件事并不冲突。

---

# 九、空 Enter 为什么不会破坏 one-shot CLI

交互 REPL 中：

```text
用户输入空行
↓
parse_command_line() → None
↓
检测 CommandRegistry 是否存在 menu
↓
存在：构造 ParsedCommand(name="menu")
↓
仍然经过 _execute() / CommandService
```

这只是 discoverability shortcut。

one-shot：

```bash
caldav-assistant today
```

仍然直接：

```text
argv
↓
run_one_shot
↓
CommandService
↓
退出
```

不会进入菜单。

---

# 十、一次完整的“修改截止日期”调用链

用户：

```text
Enter
→ Manage
→ Tasks
→ Edit Task
→ 选择任务
→ Due date
→ August5
```

调用链概念上是：

```text
REPL
↓
Navigation / Menu
↓
canonical edit command
↓
Item selector / choose_task
↓
Field menu
↓
PromptKit.ask_date
↓
TemporalParser.parse_date("August5")
↓
TaskService update/set_due
↓
CalDAVAdapter
↓
VTODO
```

旁路可以有：

```text
Undo Journal
Activity Journal
Extension hook
```

但：

- Menu 不解析 `August5`；
- Edit 不自己实现另一套日期 parser；
- CLI 不直接写 CalDAV XML；
- Activity Journal 不能覆盖 CalDAV Task 状态。

---

# 十一、数据到底放在哪里

## CalDAV — Task/Event 事实源

保存 VTODO / VEVENT 及标准字段。

```text
status
start
due
priority
completed
categories
recurrence
alarm
...
```

## SQLite — Assistant 辅助状态

可以保存：

```text
cache
current task pointer
settings
undo
activity journal
reminder dedupe
WordPress outbox
```

但它不能变成第二套 Task database。

## WordPress — 长期文字记录

保存有长期价值的工作/学习日志。

WordPress 暂时离线不能导致：

```text
done failed
start failed
edit failed
```

---

# 十二、开发者要改哪个文件

## `caldav_assistant/internal/cli/app.py`

负责：

```text
REPL / one-shot
parse command line
_execute
result rendering entry
blank Enter → guided menu discoverability
```

不负责 Task/Event 业务。

## `caldav_assistant/internal/cli/navigation.py`

负责：

```text
NavigationMenu
NavigationCommand
navigation stack
breadcrumb
history composition
leaf → CommandService
```

不负责直接改 CalDAV。

## `caldav_assistant/internal/prompts/menu.py`

负责所有通用菜单规则：

```text
number
0/back
q/cancel
?/help
search
paging
MenuView
on_unmatched client handoff
```

它不知道什么是 Task complete。

## `caldav_assistant/internal/prompts/kit.py`

统一交互积木：

```text
ask_text
ask_date
ask_datetime
choose
choose_task
choose_event
confirm
```

## `caldav_assistant/internal/presentation/`

负责把同一 View 渲染成：

```text
TXT
JSON
HTML
```

客户端不应该重新定义业务菜单。

## `caldav_assistant/builtin_extensions/software_intro.py`

负责根据 setup stage 给用户**一个明确下一步**，不再承担“先教一整套命令”的角色。

---

# 十三、增加菜单功能的正确方式

## 已经有 command

例如未来想加：

```text
Undo last change
```

如果 canonical `undo` 已存在，只增加：

```python
NavigationCommand("Undo last change", "undo")
```

不要重新实现 Undo。

## 还没有 command

正确顺序：

```text
Core Service / reusable action
↓
canonical command registration
↓
CLI composition
↓
NavigationCommand leaf
```

错误顺序：

```text
menu callback 直接操作 DB/CalDAV
↓
以后再想办法让 command 复用
```

那会重新产生菜单版业务和命令版业务两套实现。

---

# 十四、增加子菜单的正确方式

只声明结构：

```python
NavigationMenu(
    "Projects",
    (
        NavigationCommand("Project agenda", "project-agenda"),
        NavigationCommand("Project log", "project-log"),
    ),
)
```

不要写：

```python
while True:
    print("1 ...")
    value = input()
    if value == "1": ...
```

统一 Menu 已经负责选择、返回、帮助、渲染和输入恢复。

---

# 十五、扩展作者应该从 Easy API 开始

普通扩展：

```python
from caldav_assistant.easy import command, show, overdue_tasks

@command("urgent")
def urgent():
    show(overdue_tasks())
```

普通扩展不应该先理解：

```text
Context
RuntimeClient
IPC
CalDAV XML
SQLite schema
Dependency injection
```

三层 API：

```text
Easy API
↓
Object API (ctx.tasks / ctx.events / ctx.ui / ...)
↓
Full Extension API v1
↓
Internal Core
```

简单功能优先 Easy API；不要因为 Full API 强大，就把内部复杂度强迫给每个扩展作者。

---

# 十六、验收“用户不需要学习”的测试标准

代码能运行还不够。

必须验证：

### A. 完全不知道命令

```text
启动 → Enter → 数字 → 数字
```

可以到达核心功能。

### B. `0` 只退一级

```text
Root → Manage → Tasks → 0
```

结果必须是 Manage。

### C. 第三层能看到路径

```text
CalDAV Assistant > Manage > Tasks
```

### D. 菜单里可随时输入正常命令

```text
CalDAV Assistant > Logs
> today
```

必须交回正常 REPL，而不是把 `today` 判定为 invalid menu choice。

### E. 菜单与直接命令复用同一 handler

菜单 Today 与直接 `today` 最终都必须走 CommandService 的同一个 canonical command。

### F. one-shot 保持稳定

```bash
caldav-assistant today
```

执行一次以后退出。

### G. 修改共享 Menu 必须跑全套测试

因为它还被以下功能复用：

```text
settings
choose_task
choose_event
edit
add
extensions
```

所以不是只跑 navigation tests。

---

# 十七、不要再写“说了跟没说一样”的说明

无效说明往往只是：

```text
Agenda：日程
Settings：设置
Extensions：扩展
```

这只是在重复 UI label。

真正有用的说明至少回答：

```text
什么时候用？
具体按什么？
下一步会出现什么？
会修改哪里的数据？
失败以后会怎样？
开发层最终调用哪个 Service？
```

例如“Complete task”的有效说明应该说明：

```text
用户选择 Task
↓
TaskService.complete
↓
写 CalDAV STATUS:COMPLETED / COMPLETED / PERCENT-COMPLETE
↓
Activity/Undo 等辅助记录
```

而不是只写：

```text
Complete task：完成任务。
```

---

# Eighteen — English quick guide

You do not need to learn commands first.

Start `caldav-assistant`, then press **Enter** at the `>` prompt. Choose by number; `0`
goes back exactly one level. The current path is visible, e.g.:

```text
CalDAV Assistant > Manage > Tasks
```

Direct commands remain optional shortcuts and may be typed even while a menu is open.
The terminal hands unmatched command text back to the normal REPL instead of building
a second command parser inside Menu.

Developer rule:

```text
Navigation decides where to go.
Command composition chooses the canonical action.
Core Service implements business behavior.
Adapter performs external storage/platform IO.
```

Do not move business logic into Menu/Navigation.

---

# 最终原则

> **打开就能用：Enter 是发现入口，数字是基础操作，0 是一级返回，命令是快捷方式。**

> **导航有真正的树和 stack，但它不拥有 Task/Event 业务。**

> **菜单、直接命令、通知、自然语言和 Python API 最终复用同一个 Core Service。**

> **CalDAV 是 Task/Event 事实源；SQLite 是辅助状态；WordPress 是长期记录。**

> **内部可以复杂，但复杂度不能转嫁给普通用户或 Easy API 扩展作者。**
