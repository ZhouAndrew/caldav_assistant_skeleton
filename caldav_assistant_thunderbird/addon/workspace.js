"use strict";

const $ = id => document.getElementById(id);
let actionRunning = false;

const state = {
  tasks: [],
  timing: {
    accumulatedMs: 0,
    segmentStartedAtMs: null,
    source: "none",
  },
  currentWorkId: null,
  currentRef: null,
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
  const active = Boolean(task && state.currentWorkId);

  $("no-current").hidden = active;
  $("current-work").hidden = !active;
  $("task-picker-link").textContent = active ? "换 Task" : "选择 Task";
  $("actions").replaceChildren();
  $("cancel-confirm").hidden = true;

  if (!active) return;

  $("current-title").textContent = task.title || "(无标题)";
  $("current-state").textContent = "正在进行";
  $("current-state").className = "task-state working";

  const due = displayDate(task.due);
  $("current-due").textContent = due === "—" ? "没有截止日期" : "截止 " + due;

  addAction("停止", () => runWorkflow("stop"), "primary");
  addAction("完成", () => runWorkflow("complete"));
  addAction("取消", () => {$("cancel-confirm").hidden = false;}, "danger");
  updateElapsed();
}

function updateElapsed() {
  if (!state.current || !state.currentWorkId) return;
  let ms = Number(state.timing.accumulatedMs || 0);
  if (state.timing.segmentStartedAtMs) {
    ms += Math.max(0, Date.now() - state.timing.segmentStartedAtMs);
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
    if (action === "stop") {
      receipt = await AssistantExecutor.stop(task);
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
    state.tasks = await browser.ThunderbirdCalDAV.listTasks();
    state.currentWorkId = await AssistantStorage.getCurrentWorkId();
    state.currentRef = state.currentWorkId
      ? AssistantStorage.parseWorkTaskId(state.currentWorkId)
      : null;
    state.current = null;

    if (state.currentRef) {
      try {
        state.current = await browser.ThunderbirdCalDAV.getTask(
          state.currentRef.calendarId,
          state.currentRef.id,
          state.currentRef.recurrenceId || ""
        );
      } catch (_error) {
        state.current = taskByRef(state.currentRef);
      }
    }

    if (state.currentWorkId && !state.current) {
      showNotice("当前 Task 暂时无法从 Calendar 读取。", true);
    }

    state.timing = state.current
      ? await AssistantStorage.deriveWorkTiming(state.current)
      : {
          accumulatedMs: 0,
          segmentStartedAtMs: null,
          source: "none",
        };

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
    const auditChanged = Object.keys(changes).some(
      key => key.startsWith("caldavAssistant.audit.")
    );
    if (
      !changes["caldavAssistant.runtime"] &&
      !changes["caldavAssistant.currentWorkId"] &&
      !auditChanged
    ) return;
    clearTimeout(window.__caldavAssistantStorageRefresh);
    window.__caldavAssistantStorageRefresh = setTimeout(refreshAll, 100);
  });
}

setInterval(updateElapsed, 1000);
refreshAll();
