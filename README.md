# CalDAV Assistant — Frozen v1.0 施工骨架

本目录把《软件工作方式与公共 API 冻结规范 v1.0》转换成可直接施工的 Python 包骨架。

## 这份骨架冻结什么

1. **依赖方向**：谁可以导入谁、谁调用谁。
2. **模块输出**：每个模块必须向其他模块提供哪些类 / 函数 / Protocol。
3. **底层边界**：CalDAV XML/HTTP、SQLite、系统通知、IPC、WordPress transport 只能停留在 Adapter / Storage 实现层。
4. **公共 API**：`caldav_assistant.easy`、`caldav_assistant.api`、`caldav_assistant.api.v1`。
5. **同一 Core**：CLI、后台服务、通知动作、Python Extension 最终调用同一组 Service / Action。

## 阅读顺序

先看：

- `MODULE_DEPENDENCIES.md`：模块调用总表。
- `caldav_assistant/internal/bootstrap.py`：唯一装配点，说明所有模块如何接起来。
- `caldav_assistant/internal/tasks/service.py`：典型业务 Service。
- `caldav_assistant/internal/caldav/adapter.py`：底层 CalDAV 接入边界。
- `caldav_assistant/easy.py`：Scratch 化 Easy API。

## 代码状态

这是**接口骨架，不是完成实现**。大量方法故意 `raise NotImplementedError`。

这样做的目的不是“留空”，而是先冻结：

```text
调用者 -> 稳定接口 -> 可替换实现
```

具体 CalDAV library、通知 library、IPC 机制、SQLite schema 可以在这些边界内替换，而不改变上层模块。

## 核心依赖方向

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

**禁止逆向依赖**：Adapter 不调用 CLI；Storage 不调用 TaskService；业务 Service 不导入具体 OS API。
