# CalDAV Assistant 1.0.0

CalDAV Assistant 是一个 **local-first、CLI-first** 的任务与日程助手。CalDAV 保存 Task/Event 事实；后台服务负责同步、提醒和系统通知；SQLite 只保存缓存与 Assistant 辅助状态；WordPress 用于长期日志。

## v1.0.0 状态

**第一正式版。** 核心运行模型与 Public Python API 已按冻结规范 v1.0 实现并保持边界稳定。

主要能力：

- CalDAV VTODO / VEVENT 查询与修改；
- `today`、`next`、`edit`、`done`、`start`、`pause`、`resume` 等 CLI 操作；
- 轻量后台 Assistant Service、Local IPC 与自动拉起；
- Reminder Engine 与 Linux/macOS/Windows 系统通知 Adapter；
- Activity Journal；
- 持久 Undo Journal 与 `undo` CLI 命令；
- WordPress Outbox 与真实 WP-CLI transport；
- Settings、Localization、Command Registry、PromptKit/Menu；
- Extension 生命周期与失败隔离；
- Scratch-like Easy API、Object API、Full Extension API v1。

## 安装

需要 Python 3.10 或更高版本。

```bash
python -m pip install .
```

开发/源码安装：

```bash
python -m pip install -e .
```

运行：

```bash
caldav-assistant
```

或者 one-shot：

```bash
caldav-assistant today
caldav-assistant next
```

## 首次配置

进入：

```text
> settings
```

CalDAV 设置支持服务器地址、凭据、连接测试和 collection discovery。凭据通过交互式 secret 输入，不需要写在命令行中。

WordPress 长期日志使用本机 `wp`（WP-CLI）。如果 WordPress 不可达，日志先保存在 SQLite Outbox，后续重试；WordPress 不可用不会阻止 Task/Event 的 CalDAV 操作。可通过 `wordpress.path` 指定 WordPress 安装目录。

## 后台服务

CLI 会通过本地 IPC 使用同一个 Core Service。后台未运行时，正常 CLI 路径会尝试启动它。`background` 命令用于查看和管理运行状态/用户级自动启动。

## Public Python API

三层 API：

```python
from caldav_assistant.easy import *
from caldav_assistant.api import AssistantContext
from caldav_assistant.api.v1 import *
```

**普通扩展的第一入口是 `caldav_assistant.easy`。** Easy API 保持同步、短小、Scratch-like；扩展不需要直接处理 CalDAV XML、IPC、SQLite、依赖注入或操作系统通知 API。Object API 与 Full Extension API v1 面向确实需要更高级控制的扩展，而不是普通功能的必经路径。

### Task 与 Event 的边界

程序同时支持 VTODO/Task 和 VEVENT/Event，但二者不是同一种东西：

- **Task** 是要完成的工作，可以 `start()`、`pause()`、`resume()`、`complete()`；
- **Event** 是某个时间发生的事情，可以创建、修改、删除，但没有“完成”生命周期；
- `today()`、`agenda()`、`next()` 可以把 Task 与 Event 放在同一日程视图里；
- Task 生命周期动作只接受 Task。Easy API 若收到 Event，会明确拒绝，而不会把 Event 当作 Task 修改。

因此：

```python
from caldav_assistant.easy import *

complete("写报告")       # Task：允许按 UID 或标题解析
edit_event("教研会议", location="会议室")  # Event：独立 Event API
```

而不是：

```python
complete(next_event())   # 不允许：Event 不是可完成的 Task
```

### 在程序里学习和创建扩展

不需要先寻找扩展目录或阅读内部源码。进入 CLI 后：

```text
> extension guide
```

程序会直接讲解 Python Easy API、Task/Event 区别、最小扩展示例和常用积木。

创建一个最小的一文件扩展：

```text
> extension new school
```

程序会在受管理的用户扩展目录中生成 `school.py`，默认保持禁用。编辑文件后：

```text
> extension enable school
```

修改已经启用的扩展后：

```text
> extension reload school
```

查看扩展目录：

```text
> extension path
```

已有外部 `.py` 文件或包含 `__init__.py` 的扩展目录仍可使用：

```text
> extension add /path/to/my_extension.py
> extension enable my_extension
```

生成的最小扩展仍然只是普通 Easy API Python：

```python
from caldav_assistant.easy import command, show, today

@command("school")
def run():
    show(today())
```

扩展的发现、启用、禁用、重载和错误隔离由 Extension Manager 负责；**功能本身仍由 Easy API 组合，并最终调用与 CLI/后台相同的 Core Services。**

## 架构边界

```text
CLI / Background / Extension / Easy API
                |
                v
        Application Services
                |
        +-------+-------+
        |       |       |
        v       v       v
     CalDAV  Storage  Adapters
        |       |       |
        v       v       v
  Local CalDAV SQLite   OS / WP / IPC
```

CalDAV 是 Task/Event 的 Source of Truth。业务 Service 不直接写 CalDAV XML，不直接操作 SQLite，也不绑定具体 OS transport。

## 测试

GitHub Actions 在 Python 3.10 与 Python 3.12 上执行完整 `pytest` 测试集。

本地：

```bash
python -m pytest -q
```

## 版本稳定性

稳定 Public API 位于：

- `caldav_assistant.easy`
- `caldav_assistant.api`
- `caldav_assistant.api.v1`

`caldav_assistant.internal` 不属于兼容性承诺。
