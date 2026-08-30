# CalDAV Assistant — Detailed Guide / 详细使用指南

> This guide describes the user-facing behavior of the v1 CLI after the log-query and
> multi-level-menu work. The short version is: **CalDAV is truth, SQLite Activity is
> audit history, WordPress is the human long-term diary, and the Outbox is the reliable
> bridge between them.**
>
> 本指南说明 v1 CLI 的实际工作方式。最重要的一句话是：**CalDAV 是事实源，SQLite
> Activity 是行为审计历史，WordPress 是给人长期阅读的日志，Outbox 是可靠上传桥梁。**

---

## 1. 先理解四种“记录”

CalDAV Assistant 不把所有东西塞进一个“日志文件”。不同数据承担不同责任：

| 层 | 保存什么 | 是不是事实源 | 典型查询 |
|---|---|---:|---|
| CalDAV VTODO | Task 标题、计划开始、due、priority、STATUS、完成状态 | **是，Task 的事实源** | `today`, `tasks`, `current` |
| CalDAV Work VEVENT | 实际工作的开始/暂停/继续/结束区间 | **是，工作时间区间的事实源** | 完成时生成工作摘要 |
| SQLite Activity Journal | Assistant 已成功执行过的行为，例如 start/pause/resume/update/complete | 否；是审计历史 | `history today`, `history task ...` |
| WordPress daily post | 给人阅读的长期活动日志 | 否；是长期文字日志 | `history wordpress` |
| WordPress Outbox | 尚未成功送到 WordPress 的可靠消息 | 否；是传输队列 | `history pending` |

### 为什么要分层？

如果 WordPress 暂时坏了，Task 仍然必须可以完成；如果 CLI 被关闭，已经成功写进
CalDAV 的 Task 状态不能被撤销；如果网络稍后恢复，Outbox 又必须能继续上传而不重复写
同一条日志。

所以：

1. **先完成 authoritative operation（权威操作）**；
2. 再写 Activity；
3. 再把适合长期阅读的内容送到 WordPress/Outbox；
4. WordPress 失败不能反向把成功的 Task 操作变成失败。

---

## 2. 两种界面同时存在：命令 + 多级菜单

CalDAV Assistant 仍然是 **CLI-first**。菜单只是一个可选导航层，不会代替命令。

### 直接命令

适合熟悉以后、脚本、复制粘贴：

```text
today
next
current
start
pause
resume
done
edit
add
tasks
events
log Finished chapter 3
history today
history task Anki
history wordpress
history pending
```

### 多级菜单

输入：

```text
menu
```

或短命令：

```text
m
```

主菜单：

```text
CalDAV Assistant
  Agenda
  Work
  Logs
  Manage
  Help
```

每一项再进入下一层。例如：

```text
menu
  -> Logs
     -> WordPress today (real post)
```

这最终调用的仍然是：

```text
history wordpress
```

因此菜单和命令不会各维护一套业务实现。

### 为什么这很重要？

如果菜单自己实现“完成 Task”，命令 `done` 又实现另一份逻辑，半年以后两者一定会发生
行为差异。现在菜单只做 **dispatch（导航与分发）**，真正操作仍由 CommandService 中已有
命令完成。

---

## 3. `history`：正式的日志查询命令

`history` 有别名：

```text
logs
journal
```

不带参数时：

```text
history
```

会打开日志子菜单。

### 3.1 `history today`

```text
history today
```

查询的是：

```text
~/.caldav-assistant/assistant.sqlite3
```

中的 Activity Journal（通过 ActivityService/Repository 查询，不由 CLI 直接读 SQLite）。

输出会包含：

- 本地时间戳；
- action；
- object/task UID；
- metadata。

例如：

```text
Activity Journal · today · local SQLite
Entries: 3
  1. 2026-08-30T08:20:00+08:00  task_started  object=t1
     metadata={"due": "...", "priority": 4, ...}
  2. 2026-08-30T08:45:00+08:00  task_paused  object=t1
  3. 2026-08-30T09:10:00+08:00  task_resumed  object=t1
```

Activity 的作用是回答：

> “Assistant 当时到底做过什么？”

它**不负责**回答 Task 现在的 authoritative 状态。现在状态仍然看 CalDAV。

### 3.2 `history task <name>`

```text
history task Anki
```

查询指定 Task UID 的 Activity Journal 历史。

如果省略名称：

```text
history task
```

会通过 PromptKit 让你选择 Task。

适合排查：

- 我什么时候开始工作？
- 有没有 pause？
- due 是什么时候改的？
- Task 什么时候 complete？
- 某次操作是不是 Assistant 真正执行过？

### 3.3 `history wordpress`

```text
history wordpress
```

这是“真正的 WordPress 日志查询”。

它不是：

- SQLite 的副本；
- Outbox payload；
- 假装已经上传的本地缓存。

它会通过后台 Runtime 调用 WordPressService 的 CLI-only reader，再由 `WPCLIAdapter`
执行真正的 WP-CLI 查询：

1. 查找今天对应的 WordPress post；
2. 找到 post ID；
3. `wp post get <ID> --field=post_content`；
4. 把远端/本机 WordPress 中**实际存在的 post_content**返回给 CLI。

输出会明确标记：

```text
WordPress daily log · today · REAL post_content
Post ID: ...
Title: ...
Content:
...
```

如果今天没有文章，不会为了“查询”偷偷创建一篇，而是返回：

```text
No matching WordPress post exists.
```

### 3.4 `history pending`

```text
history pending
```

查看可靠 Outbox 中尚未送达的项目。

它会显示：

- Outbox id；
- operation；
- attempts；
- created time；
- request id；
- last error；
- 对 create_log，显示 pending text。

注意：

> `history pending` 说明“准备送什么”；`history wordpress` 说明“WordPress 现在真的有什么”。

两者不能互相替代。

---

## 4. `log`：真正写入长期日志

手工写日志：

```text
log Finished the physics exercise set
```

或：

```text
log
```

然后按提示输入文字。

处理顺序：

```text
CLI log
  -> WordPressService.log()
     -> durable Outbox enqueue
     -> immediate WP-CLI delivery attempt
        -> success: remove/ack Outbox + Activity wordpress_log_created
        -> failure: keep Outbox + mark error + return "upload pending"
```

这意味着即使 WordPress 临时不可用，`log` 也不是“什么都没发生”。内容首先进入持久 Outbox。

### publish 状态

长期日志 API 默认携带：

```text
post_status=publish
```

这是为了与现有真实日志脚本一致。

**安全提醒：** WordPress 的 `publish` 可能意味着文章可被网站访问。你的站点如果不是纯本地/
私有站点，请确认访问控制、主题、REST API、搜索引擎设置等符合你的隐私预期。

普通 `create_post()` API 没有被强制改成 publish；这个默认只属于“日志”语义。

---

## 5. WordPress 每日日志如何与现有 shell 脚本兼容

现有工作流的核心约定是：

```text
Month + day + weekday + year
```

例如：

```text
August 30  Sunday  2026
```

Assistant 现在查找 daily post 时兼容：

- 完整月份：`August`；
- 月份缩写：`Aug`；
- 日期必须是独立数字，避免 `30` 错匹配 `130`；
- weekday；
- year；
- 一个或多个空格都不影响判断。

所以脚本产生的：

```text
August 30  Sunday  2026
```

和 Assistant 自己标准化产生的：

```text
August 30 Sunday 2026
```

会被视为同一天的 daily post。

### 找到旧文章时

不会创建第二篇，而是：

1. 读取现有 `post_content`；
2. 在末尾追加新 block；
3. 更新原 post。

### 找不到时

Assistant 创建标准化标题：

```text
August 30 Sunday 2026
```

日志 API 会要求 `publish`。

### 防止重试重复

每次日志请求都有 request id，并在 WordPress 内容中加入不可见 marker：

```html
<!-- caldav-assistant-log:<request-id> -->
```

如果远端其实已经写成功、但本地刚好来不及确认，Outbox 重试时会先检查 marker；已经存在就不再追加
第二份可见日志。

### 为什么保存 `_logged_at`？

假设你在 23:58 写日志，但 WordPress 当时离线，第二天 00:10 才恢复。

如果按“上传成功时间”判断日期，这条日志会跑到第二天。

所以 Outbox payload 在用户写日志时就保存 `_logged_at`。重试时仍按原始行为日期追加到正确的 daily post。

---

## 6. Task 工作生命周期：现在会记录什么

### `start`

```text
start
start Anki
```

含义：**现在开始实际工作**，不是修改计划 DTSTART。

成功后：

1. CalDAV Task 状态进入工作状态；
2. Work session/Work VEVENT 开始；
3. SQLite Activity 写 `task_started`；
4. 发出 `task.started` hook；
5. 默认 WordPress work-session extension 写 `Started — <Task>` 日志。

### `pause`

```text
pause
```

只允许暂停**当前真的在工作**的 Task，不能写：

```text
pause Some Planned Task
```

成功后：

1. 当前 Work interval 被暂停/关闭；
2. SQLite Activity 写 `task_paused`；
3. 发出 `task.paused` hook；
4. WordPress 写 `Paused — <Task>`。

### `resume`

```text
resume
```

只允许继续之前 pause 的工作。

成功后：

1. 新的 Work interval 开始；
2. SQLite Activity 写 `task_resumed`；
3. 发出 `task.resumed` hook；
4. WordPress 写 `Resumed — <Task>`。

### `done`

```text
done
complete
```

Task 完成后：

1. CalDAV VTODO 写 authoritative completed/status/completed_at；
2. 当前 Work interval 正确结束；
3. Activity 写 `task_completed`；
4. Completion Log Service 根据真实 CalDAV Work VEVENT 生成完整工作摘要；
5. 完成摘要进入 WordPress Outbox，随后上传。

完成摘要比一个简单 `Completed` hook 更丰富，因此不会再额外生成一份重复的 completion hook 日志。

---

## 7. Task 与 Event 的边界

### Task

Task 是“要完成的工作”，所以可以：

```text
start
pause
resume
done
```

### Event

Event 是“发生在某个时间的事情”。

它可以：

```text
add event ...
events
edit-event
remove event ...
```

但没有：

```text
start event
pause event
resume event
done event
```

因为“会议发生过”和“Task 完成”不是同一个领域概念。

---

## 8. 多级菜单的完整映射

### Agenda

| 菜单 | 实际命令 |
|---|---|
| Today | `today` |
| Next | `next` |
| Current work | `current` |

### Work

| 菜单 | 实际命令 |
|---|---|
| Start recommended task | `start` |
| Pause current task | `pause` |
| Resume paused task | `resume` |
| Complete task | `done` |

### Logs

| 菜单 | 实际命令 |
|---|---|
| Write log | `log` |
| Activity today | `history today` |
| Task history | `history task` |
| WordPress today (real post) | `history wordpress` |
| Pending WordPress uploads | `history pending` |

### Manage

| 菜单 | 实际命令 |
|---|---|
| Add Task/Event | `add` |
| List Tasks | `tasks` |
| List Events | `events` |
| Edit Task | `edit` |
| Edit Event | `edit-event` |
| Remove Task/Event | `remove` |

### Help

等价于：

```text
help
```

---

## 9. 推荐的日常工作方式

刚开始使用时：

```text
menu
```

熟悉后：

```text
today
start
pause
resume
done
history today
history wordpress
```

排查日志上传：

```text
history pending
history wordpress
```

排查一个 Task 的行为历史：

```text
history task Anki
```

---

## 10. WordPress 离线时怎么办？

如果 `log` 返回类似：

```text
Saved locally; WordPress upload pending.
```

含义不是“失败并丢失”，而是：

- Outbox 已经持久保存；
- 即时上传失败；
- 后台 flush 可以之后重试。

先看：

```text
history pending
```

再看真实 WordPress：

```text
history wordpress
```

如果 pending 有内容、WordPress 没有，说明“本地已有，远端未到”。

如果 pending 没有、WordPress 有，说明已送达。

如果两边都没有，再去查 Activity/命令输入和 WordPress 配置。

---

## 11. 后台命令输出日志与 Activity/WordPress 日志不是一回事

开发者扩展的：

```text
run python worker.py in background
```

会把 stdout/stderr 写到：

```text
~/.caldav-assistant/run-logs/run-....log
```

这是**外部进程输出日志**。

不要与：

- `history today`（Activity Journal）；
- `history wordpress`（长期生活/工作日志）；
- `history pending`（Outbox）

混为一谈。

---

## 12. 常见排障

### 12.1 `history wordpress` 提示 runtime 不支持

通常说明 CLI 已更新，但旧后台服务还在运行。

重启：

```bash
caldav-assistant background restart
```

然后再：

```text
history wordpress
```

### 12.2 `history wordpress` 没有文章，但 `history pending` 有

WordPress 还没有成功收到日志。

检查：

- WP-CLI 是否可执行；
- WordPress path；
- `sudo`/文件权限（如果你的部署需要）；
- Outbox 的 `last_error`。

### 12.3 WordPress 明明有今天文章却找不到

匹配至少需要：

- month full 或 abbreviation；
- day；
- weekday；
- year。

例如：

```text
Aug 30 Sunday 2026
August 30 Sunday 2026
August 30  Sunday  2026
```

都可匹配。

### 12.4 为什么 Activity 有 `task_paused`，WordPress 没有 Paused？

先检查：

```text
extension list
extension errors wordpress_work_session_log
history pending
```

Activity 先于扩展 side effect 持久化，因此扩展失败时 Activity 仍可能存在。这是故意的可靠性边界。

### 12.5 为什么 `history today` 里 WordPress delivery action 比 Task action晚？

因为：

1. Task/Activity 是本地 authoritative/审计链路；
2. WordPress 是二级长期记录；
3. 网络和 WP-CLI 传输可能晚一些。

这是正常现象。

---

## 13. 开发者与扩展作者

扩展应优先使用：

```python
from caldav_assistant.easy import ...
```

或稳定的：

```python
from caldav_assistant.api import ...
from caldav_assistant.api.v1 import ...
```

不要让普通扩展直接：

- 操作 SQLite 表；
- 修改 CalDAV XML；
- 依赖 IPC 细节；
- 把 Event 当作 Task 完成；
- 绕开 WordPress Outbox 自己假装上传成功。

WordPress work-session extension 的正确模式是：

```text
Activity durable record
  -> public hook
     -> Easy API write_log
        -> WordPressService
           -> Outbox
           -> WP-CLI
```

扩展异常不能回滚已经成功的 Task 操作。

---

# English Guide

## 14. Mental model

CalDAV Assistant deliberately keeps different kinds of truth separate:

- **CalDAV VTODO** is the authoritative Task state.
- **CalDAV Work VEVENTs** are authoritative work intervals.
- **SQLite Activity Journal** is a durable audit trail of Assistant behavior.
- **WordPress daily posts** are the human-readable long-term diary.
- **WordPress Outbox** is a durable delivery queue, not a claim that remote delivery
  already happened.

A WordPress outage must never undo a successful Task operation.

## 15. Commands and menu coexist

Direct commands remain first-class:

```text
today
start
pause
resume
done
log ...
history today
history task Report
history wordpress
history pending
```

The optional nested menu is:

```text
menu
```

or:

```text
m
```

The menu dispatches to the exact same command handlers. It does not implement a second
copy of Task or log behavior.

## 16. Log queries

### Local audit history

```text
history today
```

Reads today's durable Activity Journal through the Activity API.

```text
history task Report
```

Reads Activity rows for one Task UID.

### Actual WordPress content

```text
history wordpress
```

Uses WP-CLI to locate today's existing daily post and then reads its actual
`post_content`. It does not create a post merely because you queried it.

### Pending delivery

```text
history pending
```

Shows Outbox items that still need delivery. A pending payload and an actual WordPress
post are intentionally different views.

## 17. Writing logs

```text
log Finished the report
```

is Outbox-first. The request is made durable before immediate WP-CLI delivery is
attempted. Long-term log operations default to `post_status=publish` to match the
existing daily-log workflow. Generic post creation is not globally forced to publish.

Each log request receives an idempotency marker, so retry after an uncertain remote
success does not duplicate the visible entry.

## 18. Work lifecycle logging

For Tasks:

- `start` -> `task_started` -> `task.started` -> WordPress `Started` entry.
- `pause` -> `task_paused` -> `task.paused` -> WordPress `Paused` entry.
- `resume` -> `task_resumed` -> `task.resumed` -> WordPress `Resumed` entry.
- `done` -> authoritative completion plus the richer completion summary built from
  actual CalDAV work intervals.

Events do not have this completion lifecycle.

## 19. Compatibility with existing daily-post scripts

Daily-post discovery accepts:

- full or abbreviated English month names;
- the day as an independent number;
- weekday;
- year;
- arbitrary extra whitespace.

Therefore both of these refer to the same day:

```text
August 30 Sunday 2026
August 30  Sunday  2026
```

This allows Assistant to reuse posts created by the existing shell workflow instead of
creating duplicate daily posts.

## 20. Troubleshooting checklist

If remote logs seem missing:

```text
history today
history pending
history wordpress
```

Interpret them in that order:

1. Did the Assistant record the action locally?
2. Is a WordPress operation still pending?
3. What content is actually present in WordPress now?

If `history wordpress` says the runtime does not support the query after an upgrade,
restart the background service so the CLI and Runtime use the same version.
