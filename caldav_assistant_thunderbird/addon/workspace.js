"use strict";

const $ = id => document.getElementById(id);
let actionRunning = false;

const state = {
  currentWorkId: null,
  current: null,
};

function displayDate(value) {
  if (!value || !value.icalString) return "—";
  const text = value.icalString;
  let match = /^(\d{4})(\d{2})(\d{2})$/.exec(text);
  if (match) return match[1] + "-" + match[2] + "-" + match[3];
  match = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/.exec(text);
  if (match) {
    return match[1] + "-" + match[2] + "-" + match[3] +
      " " + match[4] + ":" + match[5];
  }
  return text;
}

function showNotice(message, error = false) {
  const notice = $("notice");
  notice.textContent = message;
  notice.className = error ? "notice error" : "notice";
  notice.hidden = false;
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

  addAction("结束", () => runWorkflow("stop"), "primary");
  addAction("完成", () => runWorkflow("complete"));
  addAction("取消", () => {$("cancel-confirm").hidden = false;}, "danger");
}

async function persistUiFailure(action, task, error) {
  return AssistantStorage.persistResult({
    action,
    success: false,
    startedAt: new Date().toISOString(),
    completedAt: new Date().toISOString(),
    task: task ? {
      id: task.id,
      currentWorkId: AssistantExecutor.currentWorkIdOf(task),
      title: task.title,
    } : null,
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
    state.current = await AssistantExecutor.currentTask();
    state.currentWorkId = state.current
      ? AssistantExecutor.currentWorkIdOf(state.current)
      : null;
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
    if (!changes["caldavAssistant.currentWorkId"]) return;
    clearTimeout(window.__caldavAssistantStorageRefresh);
    window.__caldavAssistantStorageRefresh = setTimeout(refreshAll, 100);
  });
}

refreshAll();
