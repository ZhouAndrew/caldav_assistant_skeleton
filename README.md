# CalDAV Assistant 1.0.0

CalDAV Assistant 是一个 **local-first、CLI-first** 的任务与日程助手。CalDAV 保存 Task/Event 事实；后台服务负责同步、提醒和系统通知；SQLite 只保存缓存与 Assistant 辅助状态；WordPress 用于长期日志。

## v1.0.0 状态

**第一正式版。** 核心运行模型与 Public Python API 已按冻结规范 v1.0 实现并保持边界稳定。

主要能力：

- CalDAV VTODO / VEVENT 查询与修改；
- `today`、`next`、`add`、`edit`、`done`、`start`、`pause`、`resume` 等 CLI 操作；
- 轻量后台 Assistant Service、Local IPC 与自动拉起；
- Reminder Engine 与 Linux/macOS/Windows 系统通知 Adapter；
- Activity Journal；
- 持久 Undo Journal 与 `undo` CLI 命令；
- WordPress Outbox 与真实 WP-CLI transport；
- Settings、Localization、Command Registry、PromptKit/Menu；
- 官方内置扩展与用户扩展的统一生命周期、来源展示和失败隔离；
- Scratch-like Easy API、Object API、Full Extension API v1；
- PEP 561 `py.typed`、Easy API 类型 stub 与 Object API Protocol，支持 VS Code/Pylance 自动补全和类型检查；
- 由真实 Public API 自动生成的接口目录，可查询接口是否存在、签名、来源和用法。

## 文档

- [`GUIDE.md`](GUIDE.md)：完整 CLI、日志、Task/Event 工作方式与排障指南；
- [`EXTENSIONS_GUIDE.md`](EXTENSIONS_GUIDE.md)：**用户扩展与维护指南**。把扩展当作 Siri Shortcuts 一样的“小自动化”，从 `extension new`、Easy API 积木、修改/reload 到出错恢复和升级维护；
- `extension guide`：在程序内查看最短的扩展入门说明；
- `api` / `api list easy` / `api <interface>`：在程序内查看当前安装版本真实存在的 Public API。

普通用户如果只是想“加一个自己的功能”，建议先读 `EXTENSIONS_GUIDE.md`，不要从 Full API 或 `internal` 源码开始。

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

- **Task** 是要完成的工作，可以通过 `task.start_task()`、`task.pause()`、`task.resume()`、`task.complete()` 使用对象便捷方法；正式 namespace 也可用 `ctx.tasks.start(task)` 等动作；
- **Event** 是某个时间发生的事情，可以创建、修改、删除，但没有“完成”生命周期；
- `today()`、`agenda()`、`next()` 可以把 Task 与 Event 放在同一日程视图里；
- Task 生命周期动作只接受 Task。Easy API 若收到 Event，会明确拒绝，而不会把 Event 当作 Task 修改。

`task.start` 已冻结为 DTSTART-like 的计划开始时间属性，所以对象动作使用 `task.start_task()`，不能同时把 `task.start` 作为方法。

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

### 管理官方扩展与用户扩展

`extensions` 会把扩展按来源分成 **Official bundled extensions** 和 **User extensions**。官方扩展的源码随 CalDAV Assistant 版本更新，用户管理启用状态，不直接修改内置源码。

```text
> extensions
> extension official
> extension user
> extension info software_intro
> extension disable software_intro
> extension enable software_intro
> extension reset software_intro
```

`extension reset NAME` 只用于官方扩展，把它恢复到软件发行时定义的默认启用状态。官方扩展和用户扩展仍然使用同一个 ExtensionManager，因此启用、禁用、重载、错误隔离不存在第二套实现。

### 在程序里学习、创建和调试扩展

不需要先寻找扩展目录或阅读内部源码。进入 CLI 后：

```text
> extension guide
```

程序会直接讲解 Python Easy API、Task/Event 区别、官方扩展管理、最小扩展示例和常用积木。

更完整、面向普通用户独立维护的教程见：

```text
EXTENSIONS_GUIDE.md
```

它采用 Shortcut 风格的讲法：

```text
触发 -> 取数据 -> 选择/输入 -> 动作 -> 显示结果
```

创建一个最小的一文件扩展：

```text
> extension new school
```

程序会在受管理的用户扩展目录中生成 `school.py`，默认保持禁用。生成文件自带明确类型注解。即使过去删除过同名扩展并留下启用设置，新文件也会重新从禁用状态开始。

为扩展目录准备 VS Code/Pylance：

```text
> extension dev
```

该命令会在用户扩展目录中创建最小 `.vscode/settings.json`（已有文件时绝不覆盖）。然后用 VS Code 打开扩展目录，并选择**安装了 `caldav-assistant` 的同一个 Python 解释器/venv**。安装包提供：

- `caldav_assistant/py.typed`：PEP 561 typed package 标记；
- `caldav_assistant/easy.pyi`：Easy API 的参数、返回值、Task/Event 类型信息；
- `caldav_assistant.api.v1` Protocol：`ctx.tasks`、`ctx.events`、`ctx.agenda`、`ctx.ui` 等 Object API namespace 的结构化类型。

因此 Pylance 可以直接完成 `caldav_assistant.easy` 的导入补全、函数签名、hover 返回类型，并对明显的 Task/Event 类型错误给出提示。

接口是否真的已经实现，不需要猜，也不需要翻源码。CLI 直接查询实时 Public API 目录：

```text
> api
> api easy.complete
> api ctx.tasks.complete
> api exists Task.start_task
> api exists ctx.events.complete
> api search reminder
> api list easy
> api list object
> api list full
```

`api <interface>` 会显示 layer、kind、真实函数签名、来源和最小用法；`api exists <interface>` 只回答该公开接口是否真实存在。目录从当前安装版本的 `caldav_assistant.easy.__all__`、Object API Protocol 和 `caldav_assistant.api.v1` 实际导出生成，**不会把规范中尚未实现的概念接口伪装成可调用接口**。

Python 代码也可以查询同一目录：

```python
from caldav_assistant.api import api_catalog, api_describe, api_exists, api_find

assert api_exists("ctx.tasks.complete")
assert not api_exists("ctx.events.complete")

info = api_describe("easy.write_log")
print(info.signature)
print(info.usage)

for entry in api_find("reminder"):
    print(entry.path)
```

生成模板示例：

```python
from caldav_assistant.api import Agenda
from caldav_assistant.easy import command, show, today

@command("school")
def run() -> None:
    items: Agenda = today()
    show(items)
```

编辑文件后：

```text
> extension enable school
```

修改已经启用的用户扩展后：

```text
> extension reload school
```

如果扩展加载或运行 Hook 时出错，先看摘要：

```text
> extension errors
```

再看某个扩展的路径、错误和 traceback：

```text
> extension errors school
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
