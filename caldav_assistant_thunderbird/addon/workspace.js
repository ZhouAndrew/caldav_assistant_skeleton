"use strict";

const $ = id => document.getElementById(id);
let actionRunning = false;

const state = {
  calendars: [],
  tasks: [],
  runtime: null,
  settings: {},
  current: null,
};

function displayDate(value) {
  if (!value || !value.icalString) return "—";
  const text = value.icalString;
  let m = /^(\d{4})(\d{2})(\d{2})$/.exec(text);
  if (m) return m[1] + "-" + m[2] + "-" + m[3];
  m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/.exec(text);
  if (m) return m[1] + "-" + m[2] + "-" + m[3] + " " + m[4] + ":" + m[5];
  return text;
}

function formatDuration(ms) {
  const total = Math.max(0, Math.floor(Number(ms || 0) / 1000));
  const h = String(Math.floor(total / 3600)).padStart(2, "0");
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return h + ":" + m + ":" + s;
}

function sameTaskRef(ref, task) {
  return Boolean(
    ref &&
    task &&
    ref.id === task.id &&
    ref.calendarId === task.calendarId &&
    String(ref.recurrenceId || "") === String(task.recurrenceId || "")
  );
}

function taskByRef(ref) {
  return state.tasks.find(task => sameTaskRef(ref, task)) || null;
}

function writableEventCalendars() {
  return state.calendars.filter(calendar =>
    calendar.supportsEvents && !calendar.disabled && !calendar.readOnly
  );
}

async function resolveWorkCalendar(task) {
  const candidates = writableEventCalendars();
  const configured = candidates.find(calendar => calendar.id === state.settings.workCalendarId);
  if (configured) return configured.id;

  const sameCalendar = candidates.find(calendar => calendar.id === task.calendarId);
  const chosen = sameCalendar || candidates[0];
  if (!chosen) throw new Error("没有可写的 Work Calendar。请到“工具”设置。");
  return chosen.id;
}

function showNotice(message, error = false) {
  const notice = $("notice");
  notice.textContent = message;
  notice.className = error ? "notice error" : "notice";
  notice.hidden = false;
}

function clearNotice() {
  $("notice").hidden = true;
}

function addAction(label, handler, className) {
  const button = document.createElement("button");
  button.textContent = label;
  if (className) button.className = className;
  button.addEventListener("click", handler);
  $("actions").appendChild(button);
}

function render() {
  const task = state.current;
  const active = Boolean(task && state.runtime?.currentTask);

  $("no-current").hidden = active;
  $("current-work").hidden = !active;
  $("task-picker-link").textContent = active ? "换 Task" : "选择 Task";
  $("actions").replaceChildren();
  $("cancel-confirm").hidden = true;

  if (!active) return;

  $("current-title").textContent = task.title || "(无标题)";
  const paused = state.runtime.state === "paused";
  $("current-state").textContent = paused ? "已暂停" : "正在进行";
  $("current-state").className = "task-state " + (paused ? "paused" : "working");

  const due = displayDate(task.due);
  $("current-due").textContent = due === "—" ? "没有截止日期" : "截止 " + due;

  if (state.runtime.state === "working") {
    addAction("暂停", () => runWorkflow("pause"), "primary");
  } else if (state.runtime.state === "paused") {
    addAction("继续", () => runWorkflow("resume"), "primary");
  }

  addAction("完成", () => runWorkflow("complete"));
  addAction("取消", () => {$("cancel-confirm").hidden = false;}, "danger");
  updateElapsed();
}

function updateElapsed() {
  if (!state.current || !state.runtime?.currentTask) return;
  let ms = Number(state.runtime.accumulatedMs || 0);
  if (state.runtime.state === "working" && state.runtime.segmentStartedAtMs) {
    ms += Math.max(0, Date.now() - state.runtime.segmentStartedAtMs);
  }
  $("current-elapsed").textContent = formatDuration(ms);
}

async function persistUiFailure(action, task, error) {
  return AssistantStorage.persistResult({
    action,
    success: false,
    startedAt: new Date().toISOString(),
    completedAt: new Date().toISOString(),
    task: task ? {id: task.id, calendarId: task.calendarId, title: task.title} : null,
    steps: [],
    error: String(error?.message || error || "Unknown error"),
  }, "workflow");
}

async function runWorkflow(action) {
  const task = state.current;
  if (!task) return;
  actionRunning = true;
  $("actions").querySelectorAll("button").forEach(button => { button.disabled = true; });

  let receipt;
  try {
    if (action === "pause") {
      receipt = await AssistantExecutor.pause(task);
    } else if (action === "resume") {
      receipt = await AssistantExecutor.resume(task, await resolveWorkCalendar(task));
    } else if (action === "complete") {
      receipt = await AssistantExecutor.complete(task);
    } else if (action === "cancel") {
      receipt = await AssistantExecutor.cancel(task);
    } else {
      throw new Error("Unknown workflow action: " + action);
    }
  } catch (error) {
    receipt = await persistUiFailure(action, task, error);
  }

  await refreshAll();
  actionRunning = false;

  if (receipt.success) {
    showNotice("操作已完成。");
  } else {
    showNotice(receipt.error || receipt.summary || "操作失败。", true);
  }
}

async function refreshAll() {
  try {
    state.calendars = await browser.ThunderbirdCalDAV.listCalendars();
    state.tasks = await browser.ThunderbirdCalDAV.listTasks();
    state.runtime = await AssistantStorage.getRuntime();
    state.settings = await AssistantStorage.getSettings();
    state.current = null;

    if (state.runtime.currentTask) {
      try {
        state.current = await browser.ThunderbirdCalDAV.getTask(
          state.runtime.currentTask.calendarId,
          state.runtime.currentTask.id,
          state.runtime.currentTask.recurrenceId || ""
        );
      } catch (_error) {
        state.current = taskByRef(state.runtime.currentTask);
      }
    }

    if (state.runtime.currentTask && !state.current) {
      showNotice("当前 Task 暂时无法从 Calendar 读取。", true);
    }

    render();
  } catch (error) {
    await persistUiFailure("refresh", state.current, error);
    showNotice("读取当前工作失败。详细原因已经写入日志。", true);
  }
}

$("cancel-confirm-no").addEventListener("click", () => {
  $("cancel-confirm").hidden = true;
});
$("cancel-confirm-yes").addEventListener("click", async () => {
  $("cancel-confirm").hidden = true;
  await runWorkflow("cancel");
});

browser.ThunderbirdCalDAV.onItemsChanged.addListener(() => {
  if (actionRunning) return;
  clearTimeout(window.__caldavAssistantRefresh);
  window.__caldavAssistantRefresh = setTimeout(refreshAll, 250);
});

if (browser.storage?.onChanged) {
  browser.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "local" || actionRunning) return;
    if (!changes["caldavAssistant.runtime"] && !changes["caldavAssistant.settings"]) return;
    clearTimeout(window.__caldavAssistantStorageRefresh);
    window.__caldavAssistantStorageRefresh = setTimeout(refreshAll, 100);
  });
}

setInterval(updateElapsed, 1000);
refreshAll();
