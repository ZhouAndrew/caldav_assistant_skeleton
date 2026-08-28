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

Easy API 保持同步、短小、Scratch-like；扩展不需要直接处理 CalDAV XML、IPC、SQLite 或操作系统通知 API。

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
