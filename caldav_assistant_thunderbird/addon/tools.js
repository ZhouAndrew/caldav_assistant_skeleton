"use strict";

const $ = id => document.getElementById(id);
let calendars = [];

function option(select, value, label) {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = label;
  select.appendChild(item);
}

function renderResult(result) {
  const root = $("test-result");
  root.replaceChildren();
  if (!result) {
    root.textContent = "尚未测试。";
    return;
  }

  const head = document.createElement("div");
  head.className = "result-summary " + (result.success ? "ok" : "fail");
  head.textContent =
    (result.success ? "✓ " : "✗ ") + (result.summary || result.action);
  root.appendChild(head);

  const list = document.createElement("ul");
  list.className = "result-list";
  for (const step of result.steps || []) {
    const item = document.createElement("li");
    const latency =
      step.latencyMs !== undefined ? " · " + step.latencyMs + " ms" : "";
    item.textContent =
      (step.success === false ? "✗ " : "✓ ") +
      (step.name || step.operation || "步骤") +
      latency +
      (step.error ? " · " + step.error : "");
    list.appendChild(item);
  }
  root.appendChild(list);

  const traceTitle = document.createElement("h3");
  traceTitle.textContent = "底层实际执行";
  root.appendChild(traceTitle);

  const traceList = document.createElement("ul");
  traceList.className = "result-list trace-list";
  for (const trace of result.trace || []) {
    const item = document.createElement("li");
    const failed =
      trace.success === false || /error/i.test(trace.event || "");
    const duration =
      trace.details?.durationMs !== undefined
        ? " · " + trace.details.durationMs + " ms"
        : "";
    const reason =
      trace.details?.error?.message ||
      trace.details?.message ||
      "";
    item.textContent =
      (failed ? "✗ " : "✓ ") +
      (trace.timestamp || "") + " · " +
      (trace.component || "trace") + " · " +
      (trace.event || "event") +
      duration +
      (reason ? " · " + reason : "");
    traceList.appendChild(item);
  }
  if (!(result.trace || []).length) {
    const item = document.createElement("li");
    item.textContent = "没有额外底层诊断；上面的测试步骤就是完整路径。";
    traceList.appendChild(item);
  }
  root.appendChild(traceList);

  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(result, null, 2);
  root.appendChild(pre);
}

async function saveSettings() {
  const changed = await AssistantStorage.saveSettingsWithUndo({
    taskView: $("task-view").value || "incomplete",
  });

  const result = await AssistantStorage.persistResult({
    action: "settings.save",
    success: true,
    startedAt: new Date().toISOString(),
    completedAt: new Date().toISOString(),
    summary: "Task 设置已保存。",
    steps: [{
      component: "Settings",
      operation: "save defaults",
      success: true,
      details: {keys: changed.keys},
    }],
  }, "system");

  $("save-result").textContent =
    result.logSaved === false
      ? "⚠ 设置已保存，但日志保存失败。"
      : "✓ 设置已保存。";
  $("undo-settings").hidden = false;
}

async function undoSettings() {
  const restored = await AssistantStorage.undoSettings();
  if (!restored) {
    $("save-result").textContent = "没有可以撤销的设置修改。";
    $("undo-settings").hidden = true;
    return;
  }
  await load();
  $("save-result").textContent = "✓ 已撤销刚才的视图设置。";
}

async function load() {
  calendars = await browser.ThunderbirdCalDAV.listCalendars();
  const settings = await AssistantStorage.getSettings();

  $("task-view").value = settings.taskView || "incomplete";

  $("calendar-test").replaceChildren();
  for (
    const calendar of calendars.filter(
      item => item.supportsEvents && !item.disabled && !item.readOnly
    )
  ) {
    option($("calendar-test"), calendar.id, calendar.name);
  }

  $("undo-settings").hidden = !(await AssistantStorage.getSettingsUndo());
}

$("save-settings").addEventListener("click", saveSettings);
$("undo-settings").addEventListener("click", undoSettings);

$("calendar-quick").addEventListener("click", async () => {
  renderResult(await AssistantConnection.quickCalendarTest());
});

$("calendar-full").addEventListener("click", async () => {
  const calendarId = $("calendar-test").value;
  if (!calendarId) {
    renderResult(await AssistantStorage.persistResult({
      action: "connection.full-calendar-write",
      success: false,
      startedAt: new Date().toISOString(),
      completedAt: new Date().toISOString(),
      summary: "没有可写的 Calendar 可用于测试。",
      steps: [],
    }, "connection"));
    return;
  }
  renderResult(await AssistantConnection.fullCalendarWriteTest(calendarId));
});

load().catch(async error => {
  renderResult(await AssistantStorage.persistResult({
    action: "tools.load",
    success: false,
    startedAt: new Date().toISOString(),
    completedAt: new Date().toISOString(),
    summary: "工具页面读取失败：" + String(error && error.message || error),
    steps: [],
  }, "system"));
});
