#!/usr/bin/env python3
import json
import sys
import zipfile
from pathlib import Path

path = Path(sys.argv[1])
with zipfile.ZipFile(path) as z:
    assert z.testzip() is None
    names = set(z.namelist())

    required = {
        "manifest.json",
        "background.js",
        "workspace.html",
        "workspace.css",
        "workspace.js",
        "task-picker.html",
        "task-picker.js",
        "record.html",
        "record.js",
        "today.html",
        "today.js",
        "logs.html",
        "logs.js",
        "tools.html",
        "tools.js",
        "wordpress.html",
        "wordpress.js",
        "core/storage.js",
        "core/executor.js",
        "core/connection.js",
        "core/wordpress.js",
        "core/daily-log.js",
        "content/taskfix-window.js",
        "api/TaskFix/implementation.js",
        "api/TaskFix/schema.json",
        "api/ThunderbirdCalDAV/implementation.js",
        "api/ThunderbirdCalDAV/schema.json",
    }
    assert required <= names, required - names

    manifest = json.loads(z.read("manifest.json"))
    assert manifest["name"] == "CalDAV Assistant Experimental"
    assert manifest["version"] == "0.3.15"
    assert manifest["browser_specific_settings"]["gecko"]["id"] == (
        "ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net"
    )
    assert manifest["background"]["scripts"] == ["core/storage.js", "core/wordpress.js", "core/daily-log.js", "background.js"]
    assert manifest["browser_specific_settings"]["gecko"]["strict_min_version"] == "153.0.2"
    assert manifest["browser_specific_settings"]["gecko"]["strict_max_version"] == "153.1.*"
    assert "ThunderbirdCalDAV" in manifest["experiment_apis"]
    assert "storage" in manifest.get("permissions", [])
    assert "nativeMessaging" not in manifest.get("permissions", [])
    assert "http://*/*" not in manifest.get("permissions", [])
    assert "https://*/*" not in manifest.get("permissions", [])
    assert "optional_permissions" not in manifest

    background = z.read("background.js").decode()
    direct = z.read("api/ThunderbirdCalDAV/implementation.js").decode()
    schema = z.read("api/ThunderbirdCalDAV/schema.json").decode()
    workspace_html = z.read("workspace.html").decode()
    workspace = z.read("workspace.js").decode()
    task_picker_html = z.read("task-picker.html").decode()
    task_picker = z.read("task-picker.js").decode()
    storage = z.read("core/storage.js").decode()
    executor = z.read("core/executor.js").decode()
    connection = z.read("core/connection.js").decode()
    wordpress = z.read("core/wordpress.js").decode()
    logs_html = z.read("logs.html").decode()
    logs = z.read("logs.js").decode()
    tools_html = z.read("tools.html").decode()
    tools = z.read("tools.js").decode()
    wordpress_html = z.read("wordpress.html").decode()
    wordpress_page = z.read("wordpress.js").decode()
    daily_log = z.read("core/daily-log.js").decode()

    assert "browser.spaces.create" in background
    assert "CalDAV Assistant" in background

    # Direct Thunderbird provider architecture.
    assert "cal.manager.getCalendars" in direct
    assert ".getItemsAsArray(" in direct
    assert ".addItem(" in direct
    assert ".modifyItem(" in direct
    assert ".deleteItem(" in direct
    assert "getTask" in schema and "getEvent" in schema
    assert "X-CALDAV-ASSISTANT-PAUSED" in direct
    assert "X-CALDAV-ASSISTANT-TASK-UID" in direct
    assert "X-CALDAV-ASSISTANT-WORK-SESSION" in direct
    assert "X-CALDAV-ASSISTANT-WORK-OPEN" in direct

    # Production diagnostics remain available, but not on the Work screen.
    assert "caldav-assistant-experimental.log" in direct
    assert "diagnosticsInfo" in direct
    assert "readDiagnostics" in direct
    assert "clearDiagnostics" in direct
    assert "writeDiagnostic" in direct
    assert "diagnosticsInfo" in logs
    assert "技术诊断" in logs_html

    # Segmented Work UI contract: current work and Task selection are separate pages.
    assert "工作" in workspace_html
    assert "今天" in workspace_html
    assert "记录" in workspace_html
    assert "日志" in workspace_html
    assert "工具" in workspace_html
    assert "当前工作" in workspace_html
    assert 'href="task-picker.html"' in workspace_html
    assert "搜索 Task" not in workspace_html
    assert "最近结果" not in workspace_html
    assert 'id="task-view"' not in workspace_html
    assert 'id="task-calendar-filter"' not in workspace_html
    assert "AssistantExecutor.start" not in workspace
    assert "AssistantExecutor.pause" in workspace
    assert "AssistantExecutor.resume" in workspace
    assert "AssistantExecutor.complete" in workspace
    assert "AssistantExecutor.cancel" in workspace
    assert "resolveWorkCalendar" in workspace
    assert "browser.storage.onChanged" in workspace
    assert "AssistantStorage.getCurrentWorkId" in workspace
    assert "AssistantStorage.parseWorkTaskId" in workspace
    assert "runtime.currentTask" not in workspace
    # Existing workflow features are preserved while identity moves to one id.
    assert "AssistantExecutor.pause" in workspace
    assert "AssistantExecutor.resume" in workspace

    assert "选择 Task" in task_picker_html
    assert "搜索 Task" in task_picker_html
    assert 'name="task-view"' in task_picker_html
    assert 'id="task-calendar-list"' in task_picker_html
    for native_filter in (
        "throughcurrent",
        "throughtoday",
        "throughsevendays",
        "notstarted",
        "overdue",
        "completed",
        "open",
        "all",
    ):
        assert f'value="{native_filter}"' in task_picker_html
    assert "未完成" in task_picker_html
    assert "接下来七天" in task_picker_html
    assert "最近结果" not in task_picker_html
    assert "AssistantExecutor.switchAway" in task_picker
    assert "AssistantExecutor.start" in task_picker
    assert "AssistantStorage.getCurrentWorkId" in task_picker
    assert "AssistantStorage.parseWorkTaskId" in task_picker
    assert "runtime.currentTask" not in task_picker
    assert "换下当前 Task" in task_picker
    assert "开始这个 Task" in task_picker
    assert "先把“" in task_picker
    assert "resolveWorkCalendar" in task_picker
    assert "listNativeTasks" in task_picker
    assert "browser.TaskFix.getSelectedTasks" in task_picker
    assert "来自 Thunderbird 当前选择" in task_picker
    assert "优先使用 Thunderbird 原生 Tasks 列表" in task_picker_html
    taskfix_schema = z.read("api/TaskFix/schema.json").decode()
    taskfix_impl = z.read("api/TaskFix/implementation.js").decode()
    assert "getSelectedTasks" in taskfix_schema
    assert "_selectedTaskRefs" in taskfix_impl
    assert "recurrenceId" in taskfix_impl
    assert "setCalendarDisplayed" in task_picker
    assert "taskMatchesView" not in task_picker
    assert "filteredTasks" not in task_picker
    assert "createNativeTaskFilter" in direct
    assert "const Filter = window?.calFilter" in direct
    assert "const filter = new Filter()" in direct
    assert "filter.getItems(calendar)" in direct
    assert "nativeVisibleCalendars" in direct
    assert "mainCompositeCalendar" in direct
    assert "setCalendarDisplayed" in schema
    assert "listNativeTasks" in schema
    assert "recurrenceId" in task_picker
    assert "recurrenceId" in executor
    assert "taskBeforeStart" in executor
    assert "switchAway" in executor
    assert "AssistantStorage.getCurrentWorkId" in executor
    assert "AssistantStorage.makeWorkTaskId" in executor
    assert "sameTask(" not in executor
    assert "runtime.currentTask.id ===" not in executor
    assert '@mozilla.org/network/io-service;1' in direct
    assert '@mozilla.org/appshell/window-mediator;1' in direct
    assert "new URL(url)" not in direct
    assert "Services.sys.mjs" not in direct

    # One simple persistence function freezes log-before-display order.
    assert "persistResult" in storage
    assert "saveSettingsWithUndo" in storage
    assert "undoSettings" in storage
    assert "snapshot.keys" in storage
    assert 'KEY_CURRENT_WORK_ID = "caldavAssistant.currentWorkId"' in storage
    assert "getCurrentWorkId" in storage
    assert "setCurrentWorkId" in storage
    assert "makeWorkTaskId" in storage
    assert "parseWorkTaskId" in storage
    # Phase 1 compatibility: existing 0.3.15 runtime API remains until all
    # consumers have moved behind the one-id boundary.
    assert "getRuntime" in storage
    assert "setRuntime" in storage
    assert 'persistResult(receipt, "workflow")' in executor
    assert 'persistResult(result, "connection")' in connection
    assert 'persistResult(result, "wordpress")' in wordpress

    # Connection and settings live under Tools, not on the Work page.
    assert "默认 Task 视图" in tools_html
    assert "默认 Task Calendar" in tools_html
    assert "Work Calendar" in tools_html
    assert "undo-settings" in tools_html
    assert "saveSettingsWithUndo" in tools
    assert "undoSettings" in tools
    assert "previous: changed.previous" not in tools
    assert "details: {restored}" not in tools
    assert "Calendar 完整读写" in tools_html
    assert "WordPress 设置" in wordpress_html
    assert "完整读写测试" in wordpress_html
    assert "Application Password / REST" in wordpress_html
    assert "WP-CLI（兼容旧脚本）" in wordpress_html
    assert 'id="wp-path"' in wordpress_html
    assert 'id="wp-cli"' in wordpress_html
    assert 'id="wp-daily-work-log"' in wordpress_html
    assert "底层实际执行" in wordpress_page
    assert "httpRequest" in direct
    assert "curlRequest" in direct
    assert "insecureTls" in direct
    assert "isAllowedInsecureLocalHost" in direct
    assert "allowUntrustedTls" in wordpress
    assert 'id="wp-allow-untrusted-tls"' in wordpress_html
    assert "runWpCli" in direct
    assert "Subprocess.sys.mjs" in direct
    assert "Thunderbird privileged HTTP bridge" in wordpress
    assert "WordPress path is not configured for WP-CLI" in wordpress
    assert "No VTODO was created" in connection
    assert "AssistantConnection.fullCalendarWriteTest" in tools

    # WordPress Record appends one entry to one daily post; per-entry title/status
    # fields must not return to the simple UI.
    record_html = z.read("record.html").decode()
    record_js = z.read("record.js").decode()
    assert 'id="title"' not in record_html
    assert 'id="post-status"' not in record_html
    assert "每次只追加一条" in record_html
    assert "追加日志" in record_html
    assert "dailyLogTitle" in wordpress
    assert "ensureDailyLogPost" in wordpress
    assert "append + read-back daily WordPress log" in wordpress
    assert "wordpress.append-log" in wordpress
    assert "currentTimeText" in wordpress
    assert "mediaBlock" in wordpress
    assert "wp:image" in wordpress
    assert "wp:video" in wordpress
    assert "wp:audio" in wordpress
    assert "wp:file" in wordpress
    assert "今日日志" in record_js
    assert "Post ID" in record_js
    assert "Media ID" in record_js

    assert "AssistantStorage.listAudit" in logs
    assert "listAuditDates" in storage
    assert "复制这一天" in logs
    assert "copy-visible" in logs_html
    assert "copy-json" in logs_html
    assert "listDiagnosticsDates" in schema
    assert "recordClosedWorkSession" in daily_log
    assert "flushOutbox" in daily_log
    assert "dailyWorkLogEnabled" in wordpress
    assert "ExtensionUtils" in direct and "ExtensionError" in direct
    assert "CalTodo.sys.mjs" in direct and "new CalTodo()" in direct
    assert "CalEvent.sys.mjs" in direct and "new CalEvent()" in direct
    assert "calendar.getItem(" in direct
    assert "Calendar is disabled" in direct
    assert "Event end must not be before its start" in direct

    joined = b"\n".join(
        z.read(n) for n in names if n.endswith((".js", ".json", ".md", ".html"))
    )
    lowered = joined.lower()
    assert b"connectnative" not in lowered
    assert b"nativemessaging" not in lowered
    assert "apply.sh" not in names
    assert "patch_omnijar.py" not in names

print("caldav-assistant-experimental-0.3.15-xpi-contract: PASS")
