# CalDAV Assistant — Extensions as Shortcuts / 用户扩展与维护指南

> 这份文档是 `GUIDE.md` 的扩展章节，面向普通用户，而不是框架作者。
>
> 核心原则：**把扩展当作 Siri Shortcuts 一样的小自动化，而不是一个需要学习框架的“插件工程”。**
>
> 普通扩展应优先只使用：
>
> ```python
> from caldav_assistant.easy import ...
> ```
>
> 如果一个简单功能迫使你理解 CalDAV XML、SQLite、IPC、async、Adapter、依赖注入或 `internal` 模块，说明扩展写复杂了。

---

## 1. 先记住一个模型：扩展 = 小积木的排列

Siri Shortcuts 的思路不是“写一个 App”，而是：

```text
输入
  ↓
取数据
  ↓
筛选 / 选择
  ↓
执行动作
  ↓
显示结果
```

CalDAV Assistant 的 Easy API 也按这个思路使用。

例如“完成一个任务”不是一套新系统，而只是：

```text
选择 Task
  ↓
确认
  ↓
complete(task)
  ↓
show(result)
```

Python：

```python
from caldav_assistant.easy import choose_task, command, complete, confirm, show


@command("finish")
def finish() -> None:
    task = choose_task()
    if task is None:
        return

    if confirm(f"Complete {task.summary}?"):
        show(complete(task))
```

这已经是一个完整扩展。

你不需要：

- 写菜单循环；
- 找 CalDAV URL；
- 修改 VTODO XML；
- 直接操作 SQLite；
- 自己连接后台 IPC；
- 自己写 Windows/macOS/Linux 通知代码；
- 自己实现 Undo；
- 自己处理 WordPress transport。

这些复杂度应该留在程序内部。

---

## 2. 最推荐的工作流：复制、修改、重载

普通用户维护扩展时，推荐固定使用下面这条路径：

```text
extension new NAME
        ↓
修改生成的 NAME.py
        ↓
extension enable NAME
        ↓
运行命令测试
        ↓
以后修改后 extension reload NAME
        ↓
有问题看 extension errors NAME
```

例如：

```text
> extension new school
```

程序会创建一个用户扩展文件，但默认不启用。

然后：

```text
> extension enable school
```

以后改完代码：

```text
> extension reload school
```

如果坏了：

```text
> extension errors school
```

如果暂时不想处理：

```text
> extension disable school
```

这就是最重要的维护闭环。

> **用户应该永远有“先禁用，主程序继续工作”的退路。**

---

## 3. 30 秒做出第一个扩展

创建：

```text
> extension new urgent
```

打开生成的 `urgent.py`，把内容简化成：

```python
from caldav_assistant.easy import command, overdue_tasks, show


@command("urgent")
def urgent() -> None:
    show(overdue_tasks())
```

启用：

```text
> extension enable urgent
```

运行：

```text
> urgent
```

这就是一个扩展。

没有 manifest、没有插件类、没有注册表文件、没有 XML、没有额外配置。

---

## 4. Easy API 可以理解成几盒积木

普通扩展先记住下面几类就够了。

### 4.1 显示积木

```python
show(...)
```

例如：

```python
show(today())
show(overdue_tasks())
show(complete(task))
```

不要为了普通 CLI 输出重新发明自己的 UI 框架。

---

### 4.2 Task 查询积木

```python
tasks()
today_tasks()
overdue_tasks()
next_task()
find_task(...)
choose_task()
```

常见模式：

```python
task = choose_task()
if task is None:
    return
```

`None` 通常表示用户取消了选择。

---

### 4.3 Task 动作积木

```python
add_task(...)
edit_task(...)
start(...)
pause(...)
resume(...)
complete(...)
remove(...)
set_due(...)
```

例如：

```python
show(start(task))
```

或者：

```python
show(set_due(task, due))
```

这些动作最终走和 CLI 相同的 Core Service。

---

### 4.4 Event 积木

```python
events()
today_events()
next_event()
find_event(...)
choose_event()
add_event(...)
edit_event(...)
remove_event(...)
```

请特别记住：

> **Task 可以完成，Event 不“完成”。**

不要写：

```python
complete(next_event())
```

会议、课程、预约属于 Event；“写报告”“做作业”“修电脑”这类要完成的工作属于 Task。

---

### 4.5 Agenda 积木

```python
today()
agenda(days=7)
next()
```

它们可以把 Task 和 Event 放在同一个日程视图中。

例如：

```python
from caldav_assistant.easy import agenda, command, show


@command("week")
def week() -> None:
    show(agenda(days=7))
```

---

### 4.6 输入与选择积木

```python
choose(...)
choose_many(...)
confirm(...)
choose_task()
choose_event()
ask_date(...)
ask_time(...)
ask_datetime(...)
```

普通扩展不应该手写：

```python
while True:
    value = input(...)
    if value == "1":
        ...
```

应该让程序自己的 Prompt/Menu 负责数字选择、取消和一致交互。

---

### 4.7 时间积木

```python
parse_date(...)
parse_time(...)
parse_datetime(...)
ask_date(...)
ask_time(...)
ask_datetime(...)
```

例如：

```python
from caldav_assistant.easy import ask_date, choose_task, command, set_due, show


@command("redue")
def redue() -> None:
    task = choose_task()
    if task is None:
        return

    due = ask_date("New due date")
    if due is None:
        return

    show(set_due(task, due))
```

这样输入 `August5`、`Aug5`、`tomorrow` 等日期时，扩展与 CLI 使用同一个 TemporalParser。

---

### 4.8 Reminder / Notification 积木

```python
remind(...)
notify(...)
snooze(...)
```

简单通知：

```python
from caldav_assistant.easy import command, notify


@command("ping")
def ping() -> None:
    notify("CalDAV Assistant", "This is a test notification")
```

创建提醒：

```python
from caldav_assistant.easy import command, remind, show


@command("report-reminder")
def report_reminder() -> None:
    show(remind("Submit report", "tomorrow 17:00"))
```

扩展不需要知道 Linux DBus、Windows Toast 或 macOS Notification API。

---

### 4.9 WordPress 长期日志积木

```python
write_log(...)
```

例如：

```python
from caldav_assistant.easy import command, write_log, show


@command("study-log")
def study_log() -> None:
    show(write_log("Finished today's vocabulary review"))
```

`write_log()` 走程序已有的 WordPressService + Outbox。

不要在普通扩展里自己执行：

```text
wp post create ...
```

否则你会绕开 Outbox、重试、幂等和 Activity 边界。

---

## 5. 像 Shortcut 一样思考：常用组合配方

### 配方 A：查看 → 显示

```text
取今天任务
  ↓
显示
```

```python
@command("mytasks")
def mytasks() -> None:
    show(today_tasks())
```

### 配方 B：选择 → 确认 → 动作

```text
选 Task
  ↓
确认
  ↓
完成
```

```python
@command("finish")
def finish() -> None:
    task = choose_task()
    if task is not None and confirm(f"Complete {task.summary}?"):
        show(complete(task))
```

### 配方 C：选择 → 输入 → 修改

```text
选 Task
  ↓
问日期
  ↓
修改 due
```

```python
@command("move-due")
def move_due() -> None:
    task = choose_task()
    if task is None:
        return

    due = ask_date("New due date")
    if due is not None:
        show(set_due(task, due))
```

### 配方 D：菜单 → 分支 → 复用积木

```python
from caldav_assistant.easy import choose, command, overdue_tasks, show, today, today_events


@command("school")
def school() -> None:
    action = choose(
        ("Today", "Overdue", "Events"),
        title="School",
    )

    if action == "Today":
        show(today())
    elif action == "Overdue":
        show(overdue_tasks())
    elif action == "Events":
        show(today_events())
```

这已经足以完成大量个人自动化。

---

## 6. 一个可长期维护的扩展应该长什么样

推荐结构：

```python
from caldav_assistant.easy import (
    ask_date,
    choose_task,
    command,
    complete,
    confirm,
    set_due,
    show,
)


def _pick_task():
    return choose_task()


def _finish() -> None:
    task = _pick_task()
    if task is None:
        return
    if confirm(f"Complete {task.summary}?"):
        show(complete(task))


def _change_due() -> None:
    task = _pick_task()
    if task is None:
        return
    due = ask_date("New due date")
    if due is not None:
        show(set_due(task, due))


@command("my-work")
def my_work() -> None:
    # Keep the public command small. Put reusable steps in small helpers.
    _finish()
```

维护原则：

1. 一个函数只做一件小事；
2. 重复两次以上的交互就提成 helper；
3. 数据修改只走 Easy/Object API；
4. 用户取消时直接 `return`；
5. 动作结果用 `show()` 显示；
6. 不保存另一套 Task 状态；
7. 不依赖 `caldav_assistant.internal`。

---

## 7. 怎样修改生成模板而不把它越改越复杂

`extension new NAME` 生成的是一个较完整的教学模板。

它的正确用法是：

> **删掉不用的部分，而不是继续往里面堆框架。**

例如你只需要“显示 overdue”，就保留：

```python
from caldav_assistant.easy import command, overdue_tasks, show


@command("urgent")
def urgent() -> None:
    show(overdue_tasks())
```

不要因为模板里有菜单，就认为每个扩展都必须有菜单。

不要因为 Python 支持 class，就认为扩展必须写 class。

不要因为有 Full API，就认为 Easy API 是“不专业”。

Easy API 本来就是正式公共 API，而且普通扩展优先级最高。

---

## 8. 独立维护：你真正需要知道的命令

### 看有哪些扩展

```text
extensions
```

### 看用户扩展

```text
extension user
```

### 看官方扩展

```text
extension official
```

### 创建

```text
extension new NAME
```

### 看文件在哪里

```text
extension path
```

### 看详细信息

```text
extension info NAME
```

### 启用

```text
extension enable NAME
```

### 禁用

```text
extension disable NAME
```

### 修改后重载

```text
extension reload NAME
```

### 看全部扩展错误

```text
extension errors
```

### 看单个扩展 traceback

```text
extension errors NAME
```

### 加入已有 `.py`

```text
extension add /path/to/file.py
```

### VS Code / Pylance 准备

```text
extension dev
```

这组命令应该足以完成日常维护。

---

## 9. 最简单的排错顺序

扩展出错时，不要一开始就看 Core 源码。

按固定顺序：

```text
1. extension info NAME
2. extension errors NAME
3. extension disable NAME
4. 修改文件
5. extension enable NAME
   或 extension reload NAME
6. 再运行命令
```

如果主程序仍然可以运行，说明失败隔离正在正常工作。

### 最常见错误 1：忘了导入

错误：

```python
show(today())
```

但没有导入 `today`。

修正：

```python
from caldav_assistant.easy import show, today
```

### 最常见错误 2：用户取消后继续使用 None

错误：

```python
task = choose_task()
show(complete(task))
```

推荐：

```python
task = choose_task()
if task is None:
    return
show(complete(task))
```

### 最常见错误 3：把 Event 当 Task

错误：

```python
complete(next_event())
```

应该改成 Event 自己的 API，例如：

```python
edit_event(...)
```

### 最常见错误 4：命令名冲突

如果已有 `school` 命令，就不要静默覆盖。

换一个名字：

```python
@command("school-tools")
```

除非你确实在写高级扩展并明确知道 override 的后果。

---

## 10. 修改扩展时，怎样保证“改坏了也容易恢复”

普通用户最安全的习惯：

```text
修改前：扩展仍可运行
       ↓
编辑文件
       ↓
extension reload NAME
       ↓
立即运行一次最小测试
       ↓
失败 → extension errors NAME
       ↓
必要时 extension disable NAME
```

如果改动较大，推荐先复制文件：

```text
school.py
school_backup.py.disabled
```

或者使用 Git 保存自己的扩展目录。

扩展不应该拥有不可恢复的“隐藏数据库结构”。

Task/Event 状态仍然由 CalDAV Core 管理，用户扩展只是调用公开动作。

---

## 11. 升级 CalDAV Assistant 后怎样维护自己的扩展

升级后先做三件事：

```text
extensions
api
extension errors
```

然后测试自己最常用的命令。

如果怀疑某个 Easy API 是否仍然存在：

```text
api easy.complete
api easy.ask_date
api easy.write_log
```

或者：

```text
api exists easy.complete
```

不要通过阅读 `internal` 猜当前版本能力。

Public API 的稳定边界是：

```text
caldav_assistant.easy
caldav_assistant.api
caldav_assistant.api.v1
```

而：

```text
caldav_assistant.internal
```

不属于扩展兼容承诺。

---

## 12. 用 `api` 命令当作扩展的“积木目录”

当你忘记函数名时，不要去 Google，也不必翻源码。

可以直接：

```text
api list easy
api search reminder
api search task
api easy.complete
api easy.write_log
```

把它理解成 Siri Shortcuts 的“搜索动作”。

你的思考方式应该是：

> “我要一个选择 Task 的动作”
>
> 而不是：
>
> “我要找到 TaskSelector 的内部实现类在哪个 package。”

这正是 Public API 存在的意义。

---

## 13. VS Code 不是必须，但可以让维护更简单

运行：

```text
extension dev
```

然后用 VS Code 打开：

```text
extension path
```

显示的扩展目录。

选择安装了 `caldav-assistant` 的 Python interpreter/venv。

程序已经提供：

- `py.typed`；
- `easy.pyi`；
- Object API Protocol。

因此编辑器可以帮助你：

- 自动补全 `complete()`；
- 查看函数签名；
- 识别 Task/Event 类型；
- 提醒拼错的函数；
- 找到明显的类型错误。

但这只是辅助。

一个 5 行 Easy API 扩展不应该依赖 IDE 才能理解。

---

## 14. 什么时候才需要 Object API？

如果 Easy API 已经能完成目标，就不要升级复杂度。

Easy API：

```python
from caldav_assistant.easy import choose_task, complete, show


task = choose_task()
if task is not None:
    show(complete(task))
```

当你确实需要较明确的 namespace、服务组合或高级控制时，再使用：

```python
from caldav_assistant.api import AssistantContext
```

Object API 常见 namespace：

```text
ctx.tasks
ctx.events
ctx.agenda
ctx.reminders
ctx.notifications
ctx.wordpress
ctx.ui
ctx.time
ctx.commands
ctx.activity
ctx.settings
ctx.session
```

普通个人自动化不需要为了“看起来专业”而改成 ctx。

---

## 15. 什么时候才需要 Full Extension API v1？

只有在这些情况才优先考虑 Full API：

- Hook；
- 高级生命周期集成；
- 自定义 Agenda/Reminder rule；
- 复杂服务组合；
- 明确需要稳定异常类型；
- Easy/Object API 确实缺少必要能力。

导入：

```python
from caldav_assistant.api.v1 import ...
```

Full API 是“高级入口”，不是“正确入口”。

普通用户扩展依然应该优先 Easy API。

---

## 16. 普通扩展不要做的事情

### 不要直接 import internal

```python
from caldav_assistant.internal... import ...
```

这是最重要的维护禁区。

### 不要直接编辑 CalDAV XML

不要为了完成 Task 自己拼 VTODO。

使用：

```python
complete(task)
```

### 不要直接改 SQLite

Activity、Undo、Outbox、设置都有自己的 Service/API。

### 不要自己实现第二套 Task 状态

例如不要创建：

```python
my_tasks.json
```

然后自己保存 completed/current 状态。

Task/Event 事实仍然在 CalDAV。

### 不要让 WordPress 决定 Task 是否完成

`write_log()` 是长期记录，不是 Task 状态。

### 不要默认引入 async

Easy API 的正式方向是同步、直观。

如果一个普通扩展只是“选任务然后完成”，就不应该出现 event loop。

### 不要把扩展写成 mini framework

如果你开始写：

- BasePlugin；
- PluginFactory；
- AbstractCommand；
- 自己的 router；
- 自己的 dependency container；

先问一句：

> 这个功能能不能用 3～6 个 Easy API 积木直接表达？

大多数个人自动化可以。

---

## 17. 一个“Shortcut 风格”扩展设计检查表

写之前先用自然语言描述：

```text
触发：输入命令 school
输入：无
取数据：今天的 agenda
筛选：category=school（如果需要）
交互：可选
动作：显示
结果：用户看到日程
```

然后把每一步映射到 Easy API。

例如：

```text
触发        → @command("school")
取数据      → agenda(...)
用户选择    → choose(...), choose_task()
问日期      → ask_date(...)
修改        → set_due(...)
完成        → complete(...)
长期记录    → write_log(...)
显示        → show(...)
通知        → notify(...)
```

如果大部分步骤都找不到对应 Public API，再考虑 Object/Full API。

---

## 18. 推荐的文件规模

这不是硬限制，但对个人扩展很实用：

- 5～20 行：非常好；
- 20～80 行：正常；
- 80～200 行：考虑拆 helper；
- 200 行以上：检查是不是把内部框架搬进了扩展。

一个用户扩展可以只有一个 `.py` 文件，这是正式支持场景。

不要为了“工程化”而强制 package 化。

---

## 19. 示例：学校快捷动作

下面是一个仍然容易维护、但比最小示例更实用的扩展：

```python
from caldav_assistant.easy import (
    agenda,
    ask_date,
    choose,
    choose_task,
    command,
    complete,
    confirm,
    set_due,
    show,
)


_ACTIONS = (
    "This week",
    "Complete a task",
    "Change due date",
)


def _complete_one() -> None:
    task = choose_task()
    if task is None:
        return
    if confirm(f"Complete {task.summary}?"):
        show(complete(task))


def _change_due() -> None:
    task = choose_task()
    if task is None:
        return
    due = ask_date("New due date")
    if due is not None:
        show(set_due(task, due))


@command("school")
def school() -> None:
    action = choose(_ACTIONS, title="School")

    if action == "This week":
        show(agenda(days=7, category="school"))
    elif action == "Complete a task":
        _complete_one()
    elif action == "Change due date":
        _change_due()
```

它的维护成本仍然很低：

- 只有一个文件；
- 只用 Easy API；
- 每个 helper 很短；
- 没有数据库；
- 没有 async；
- 没有内部模块；
- 改坏后可以直接 disable。

---

## 20. 示例：把常用操作做成一个小菜单

```python
from caldav_assistant.easy import (
    choose,
    command,
    overdue_tasks,
    show,
    today,
    today_events,
    today_tasks,
)


@command("desk")
def desk() -> None:
    action = choose(
        ("Agenda", "Tasks", "Overdue", "Events"),
        title="Desk",
    )

    if action == "Agenda":
        show(today())
    elif action == "Tasks":
        show(today_tasks())
    elif action == "Overdue":
        show(overdue_tasks())
    elif action == "Events":
        show(today_events())
```

这种扩展非常接近 Shortcut：

> 一个入口 + 几个现成动作。

---

## 21. 示例：完成任务后写一条长期日志

如果这是你明确想要的个人 workflow，可以组合：

```python
from caldav_assistant.easy import (
    choose_task,
    command,
    complete,
    confirm,
    show,
    write_log,
)


@command("finish-log")
def finish_log() -> None:
    task = choose_task()
    if task is None:
        return

    if not confirm(f"Complete {task.summary}?"):
        return

    result = complete(task)
    show(result)

    if result is not None and result.success:
        show(write_log(f"Completed — {task.summary}"))
```

这里的顺序很重要：

```text
Task completion
   ↓
CalDAV authoritative success
   ↓
optional long-term log
```

WordPress 失败不能把已经成功的 Task completion 变回失败。

---

## 22. 官方扩展与用户扩展的维护边界

官方扩展：

```text
extension official
```

其源码随应用版本维护。

普通用户通常只做：

```text
extension enable NAME
extension disable NAME
extension reload NAME
extension reset NAME
extension errors NAME
```

用户扩展：

```text
extension user
```

其源码由你自己维护。

不要直接修改 bundled official extension 文件来实现个人定制，因为升级时可能被替换。

如果喜欢某个官方扩展的思路，推荐新建一个用户扩展，用 Easy API 实现自己的版本。

---

## 23. “我不会 Python 很多，可以维护吗？”

可以。最基本只需要理解：

### 导入动作

```python
from caldav_assistant.easy import command, show, today
```

### 定义一个命令

```python
@command("today2")
def today2() -> None:
    show(today())
```

### 变量

```python
task = choose_task()
```

### 判断

```python
if task is None:
    return
```

### 调一个动作

```python
show(complete(task))
```

这已经能做很多东西。

不需要先学习 Python class、decorator 原理、asyncio、typing 泛型或框架设计。

`@command(...)` 先把它理解为：

> “把下面这个函数变成 Assistant 命令”。

以后有兴趣再研究 Python 细节。

---

## 24. 最终维护规则

普通用户扩展尽量遵守下面 10 条：

1. **Easy API first**。
2. 一个扩展可以只有一个 `.py` 文件。
3. 一个命令尽量只完成一个清晰目标。
4. 输入/菜单使用 `choose*` / `ask_*` / `confirm`。
5. Task/Event 修改只使用公共动作 API。
6. 用户取消就 `return`，不要强行继续。
7. 修改后用 `extension reload NAME`。
8. 出错先用 `extension errors NAME`，必要时 disable。
9. 不 import `caldav_assistant.internal`。
10. 只有 Easy API 确实不够时，才升级到 Object/Full API。

如果以后扩展系统继续增加能力，也应保持这条产品原则：

> **新增“积木”，而不是新增“用户必须学习的框架”。**

---

# English quick reference

## A. The mental model

Treat a user extension like a Shortcut:

```text
trigger -> get data -> choose/filter -> action -> show result
```

Prefer:

```python
from caldav_assistant.easy import ...
```

A small extension should not require knowledge of CalDAV XML, SQLite, IPC, adapters,
async runtimes, dependency injection, or internal modules.

## B. Normal lifecycle

```text
extension new NAME
extension enable NAME
extension reload NAME
extension errors NAME
extension disable NAME
```

Use `extension path` to locate user files and `extension dev` for optional VS Code/Pylance setup.

## C. Public bricks

Typical Easy API groups:

```text
show

tasks / today_tasks / overdue_tasks / next_task / choose_task
start / pause / resume / complete / set_due

events / today_events / next_event / choose_event
add_event / edit_event / remove_event

today / agenda / next

choose / choose_many / confirm
ask_date / ask_time / ask_datetime

remind / notify / snooze
write_log
command
```

Tasks have a completion lifecycle. Events do not.

## D. Upgrade path

Use Easy API first. Use Object API only when its namespaces are actually useful, and Full Extension API v1 only for advanced hooks/integration.

Stable extension imports are:

```text
caldav_assistant.easy
caldav_assistant.api
caldav_assistant.api.v1
```

Do not depend on:

```text
caldav_assistant.internal
```

## E. Recovery rule

If a user extension breaks:

```text
extension errors NAME
extension disable NAME
```

The main Assistant should continue working. Fix the file, then enable/reload again.
