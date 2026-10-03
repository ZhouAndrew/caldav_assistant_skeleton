"use strict";

const $ = id => document.getElementById(id);
let actionRunning = false;

const state = {
  calendars: [],
  tasks: [],
  selected: null,
  currentWorkId: null,
  currentRef: null,
  settings: {},
  taskView: "open",
  filtersInitialized: false,
  selectionSource: "",
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

function sameTaskRef(ref, task) {
  return Boolean(
    ref &&
    task &&
    ref.id === task.id &&
    ref.calendarId === task.calendarId &&
    String(ref.recurrenceId || "") === String(task.recurrenceId || "")
  );
}

function normalizeTaskView(value) {
  const aliases = {
    incomplete: "open",
    today: "throughtoday",
  };
  const normalized = aliases[String(value || "")] || String(value || "open");
  return [
    "throughcurrent",
    "throughtoday",
    "throughsevendays",
    "notstarted",
    "overdue",
    "completed",
    "open",
    "all",
  ].includes(normalized)
    ? normalized
    : "open";
}

function taskByRef(ref) {
  return state.tasks.find(task => sameTaskRef(ref, task)) || null;
}

function taskState(task) {
  if (!task) return {label: "未选择", css: ""};
  if (sameTaskRef(state.currentRef, task)) {
    return task.paused
      ? {label: "已暂停", css: "paused"}
      : {label: "正在进行", css: "working"};
  }
  if (task.status === "COMPLETED") return {label: "已完成", css: "completed"};
  if (task.status === "CANCELLED") return {label: "已取消", css: "cancelled"};
  if (task.paused) return {label: "已暂停", css: "paused"};
  if (task.status === "IN-PROCESS") return {label: "进行中", css: "working"};
  return {label: "未开始", css: ""};
}

function enabledTaskCalendars() {
  return state.calendars.filter(calendar => calendar.supportsTasks && !calendar.disabled);
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
  return chosen?.id || null;
}

function showNotice(message, error = false) {
  const notice = $("notice");
  notice.textContent = message;
  notice.className = error ? "notice error" : "notice";
  notice.hidden = false;
}

function renderFilters() {
  for (const radio of document.querySelectorAll('input[name="task-view"]')) {
    radio.checked = radio.value === state.taskView;
  }

  const list = $("task-calendar-list");
  list.replaceChildren();
  for (const calendar of enabledTaskCalendars()) {
    const label = document.createElement("label");
    label.className = "native-calendar-row";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = Boolean(calendar.displayed);
    checkbox.disabled = Boolean(calendar.disabled);
    checkbox.addEventListener("change", async () => {
      checkbox.disabled = true;
      try {
        await browser.ThunderbirdCalDAV.setCalendarDisplayed(
          calendar.id,
          checkbox.checked
        );
        await refreshAll(true);
      } catch (error) {
        checkbox.checked = !checkbox.checked;
        checkbox.disabled = false;
        await persistUiFailure("calendar-visibility", state.selected, error);
        showNotice("修改 Thunderbird Calendar 可见性失败。", true);
      }
    });

    const text = document.createElement("span");
    text.textContent = calendar.name + (calendar.readOnly ? " · 只读" : "");
    label.append(checkbox, text);
    list.appendChild(label);
  }
}

function renderCurrentStrip() {
  const task = taskByRef(state.currentRef);
  const strip = $("current-strip");
  if (!task) {
    strip.hidden = true;
    return;
  }
  const stateText = task.paused ? "已暂停" : "正在进行";
  $("current-strip-text").textContent =
    "当前：" + (task.title || "(无标题)") + " · " + stateText;
  strip.hidden = false;
}

function renderTasks() {
  $("task-list").replaceChildren();
  const tasks = state.tasks;
  if (!tasks.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "没有匹配的 Task";
    $("task-list").appendChild(empty);
    return;
  }

  for (const task of tasks) {
    const row = document.createElement("div");
    row.className = "item" + (sameTaskRef(state.selected, task) ? " selected" : "");

    const title = document.createElement("div");
    title.className = "item-title";
    title.textContent = task.title || "(无标题)";

    const meta = document.createElement("div");
    meta.className = "item-meta";
    const status = taskState(task).label;
    const due = displayDate(task.due);
    meta.textContent = due === "—" ? status : status + " · 截止 " + due;

    row.append(title, meta);
    row.addEventListener("click", () => {
      state.selected = task;
      state.selectionSource = "assistant";
      renderTasks();
      renderSelection();
    });
    $("task-list").appendChild(row);
  }
}

function addAction(label, handler, className) {
  const button = document.createElement("button");
  button.textContent = label;
  if (className) button.className = className;
  button.addEventListener("click", handler);
  $("actions").appendChild(button);
}

function renderSelection() {
  const task = state.selected;
  $("no-selection").hidden = Boolean(task);
  $("selection").hidden = !task;
  $("actions").replaceChildren();
  $("flow-note").textContent = "";
  if (!task) return;

  const sourceNote = state.selectionSource === "thunderbird"
    ? "来自 Thunderbird 当前选择。"
    : "";

  $("selected-title").textContent = task.title || "(无标题)";
  const view = taskState(task);
  $("selected-state").textContent = view.label;
  $("selected-state").className = "task-state " + view.css;
  const due = displayDate(task.due);
  $("selected-due").textContent = due === "—" ? "没有截止日期" : "截止 " + due;

  const finished = task.status === "COMPLETED" || task.status === "CANCELLED";
  const current = taskByRef(state.currentRef);

  if (finished) {
    $("flow-note").textContent = [sourceNote, "这个 Task 已结束。"].filter(Boolean).join(" ");
    return;
  }

  if (sameTaskRef(state.currentRef, task)) {
    $("flow-note").textContent = [sourceNote, "这个 Task 就是当前工作。"].filter(Boolean).join(" ");
    return;
  }

  if (current) {
    addAction("换下当前 Task", runPutAside, "primary");
    $("flow-note").textContent = [
      sourceNote,
      "先把“" + (current.title || "(无标题)") + "”换下来；完成后再开始这个 Task。",
    ].filter(Boolean).join(" ");
    return;
  }

  addAction("开始这个 Task", runStart, "primary");
  $("flow-note").textContent = sourceNote;
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

async function runPutAside() {
  const target = state.selected;
  const current = taskByRef(state.currentRef);
  if (!target || !current) return;

  actionRunning = true;
  $("actions").querySelectorAll("button").forEach(button => { button.disabled = true; });
  let receipt;
  try {
    receipt = await AssistantExecutor.switchAway(current);
  } catch (error) {
    receipt = await persistUiFailure("switch-away", current, error);
  }

  // Keep the user's target choice across provider notifications from putting
  // the current Task aside. The steps remain separate; this does not start it.
  state.selected = target;
  await refreshAll(true);
  actionRunning = false;

  if (receipt.success) {
    showNotice("已结束当前工作，并把原 Task 恢复到开始前的未完成状态。现在可以开始“" + (target.title || "(无标题)") + "”。");
  } else {
    showNotice(receipt.error || receipt.summary || "换下当前 Task 失败。", true);
  }
}

async function runStart() {
  const task = state.selected;
  if (!task) return;

  actionRunning = true;
  $("actions").querySelectorAll("button").forEach(button => { button.disabled = true; });
  let receipt;
  try {
    receipt = await AssistantExecutor.start(task, await resolveWorkCalendar(task));
  } catch (error) {
    receipt = await persistUiFailure("start", task, error);
  }

  if (receipt.success) {
    window.location.href = "workspace.html";
    return;
  }

  state.selected = task;
  await refreshAll(true);
  actionRunning = false;
  showNotice(receipt.error || receipt.summary || "开始 Task 失败。", true);
}

async function refreshAll(preserveSelection = true) {
  try {
    const selectedRef = preserveSelection && state.selected
      ? {
          id: state.selected.id,
          calendarId: state.selected.calendarId,
          recurrenceId: state.selected.recurrenceId || "",
        }
      : null;

    state.calendars = await browser.ThunderbirdCalDAV.listCalendars();
    state.currentWorkId = await AssistantStorage.getCurrentWorkId();
    state.currentRef = state.currentWorkId
      ? AssistantStorage.parseWorkTaskId(state.currentWorkId)
      : null;
    state.settings = await AssistantStorage.getSettings();

    if (!state.filtersInitialized) {
      state.taskView = normalizeTaskView(state.settings.taskView);
      state.filtersInitialized = true;
    }

    state.tasks = await browser.ThunderbirdCalDAV.listNativeTasks({
      filter: state.taskView,
      searchText: $("task-search").value,
    });

    if (selectedRef) {
      state.selected = taskByRef(selectedRef);
      state.selectionSource = state.selected ? "assistant" : "";
    } else {
      const nativeRefs = await browser.TaskFix.getSelectedTasks();
      if (nativeRefs.length === 1) {
        const ref = nativeRefs[0];
        try {
          state.selected = await browser.ThunderbirdCalDAV.getTask(
            ref.calendarId,
            ref.id,
            ref.recurrenceId || ""
          );
          state.selectionSource = "thunderbird";
        } catch (error) {
          state.selected = null;
          state.selectionSource = "";
          await persistUiFailure("native-selection-read", null, error);
          showNotice("Thunderbird 当前选中的 Task 无法读取。", true);
        }
      } else if (nativeRefs.length > 1) {
        state.selected = null;
        state.selectionSource = "";
        showNotice("Thunderbird 当前选中了多个 Task。请先只选一个，再回到这里。", true);
      } else {
        state.selected = null;
        state.selectionSource = "";
      }
    }

    renderFilters();
    renderCurrentStrip();
    renderTasks();
    renderSelection();
  } catch (error) {
    await persistUiFailure("refresh", state.selected, error);
    showNotice("读取 Task 失败。详细原因已经写入日志。", true);
  }
}

let searchTimer = null;
$("task-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => refreshAll(true), 120);
});

for (const radio of document.querySelectorAll('input[name="task-view"]')) {
  radio.addEventListener("change", async event => {
    if (!event.target.checked) return;
    state.taskView = normalizeTaskView(event.target.value);
    state.selected = null;
    state.selectionSource = "";
    await refreshAll(false);
  });
}

browser.ThunderbirdCalDAV.onItemsChanged.addListener(() => {
  if (actionRunning) return;
  clearTimeout(window.__caldavAssistantRefresh);
  window.__caldavAssistantRefresh = setTimeout(() => refreshAll(true), 250);
});

if (browser.storage?.onChanged) {
  browser.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "local") return;
    if (changes["caldavAssistant.settings"]) {
      state.settings = changes["caldavAssistant.settings"].newValue || {};
      state.taskView = normalizeTaskView(state.settings.taskView);
      state.filtersInitialized = true;
    }
    if (
      !changes["caldavAssistant.settings"] &&
      !changes["caldavAssistant.currentWorkId"]
    ) return;
    refreshAll(true);
  });
}

refreshAll(false);
