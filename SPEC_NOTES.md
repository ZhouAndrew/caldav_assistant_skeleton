# 冻结规范中需要开发者明确知道的接口注意事项

这不是修改冻结规范，而是把实现时不能静默忽略的接口细节标出来。

## 1. `Task.start` 属性 与 `task.start()` 方法存在 Python 名称冲突

冻结规范同时列出：

```python
task.start        # Task 的开始日期/时间属性
```

以及“对象 API 可以支持”：

```python
task.start()      # 开始这个任务的便捷动作
```

在 Python 中，同一个对象不能同时把 `start` 作为普通数据属性，又把同名 `start` 作为可调用方法。

因此本骨架不偷偷改掉冻结属性：

- 保留 `task.start` 数据属性；
- 保留正式动作路径 `ctx.tasks.start(task)`；
- Easy API 保留 `start(task)`；
- 对象便捷方法暂写作 `task.start_task()`。

如果以后必须要求 `task.start()` 也成为 v1 公共 API，需要先对“时间属性叫什么”做一次明确 API 决议；不能由施工者自行猜。

## 2. CLI 与后台的职责已按冻结规范强制拆开

CLI 侧不构造：

- `TaskService`
- `EventService`
- `CalDAVAdapter`
- OS Notification Adapter
- WordPress Transport

CLI 使用：

```text
Remote*API Proxy
 -> RuntimeClient
 -> Local IPC
 -> RuntimeDispatcher
 -> Background-owned Core Service
```

这避免了“CLI 一套 Task 逻辑、后台又一套 Task 逻辑”。

## 3. 具体库没有在骨架里被冻结

`LibraryCalDAVAdapter`、平台通知 Adapter、IPC Adapter、WordPress transport 都只是实现插槽。

只有上层接口被冻结。若某个库无法满足冻结行为，应替换库，而不是修改 Service/CLI/Public API。
