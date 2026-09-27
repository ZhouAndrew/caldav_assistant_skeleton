const $ = (id) => document.getElementById(id);
let snapshot = null;

async function nativeRequest(payload) {
  const response = await messenger.runtime.sendMessage({
    target: "caldav-assistant-native",
    payload,
  });
  if (!response) {
    throw new Error("No response from CalDAV Assistant native host.");
  }
  if (!response.ok) {
    const detail = response.error || {};
    throw new Error(detail.message || detail.type || "CalDAV Assistant request failed.");
  }
  return response.result;
}

function showMessage(text, kind = "") {
  const box = $("message");
  box.textContent = text || "";
  box.className = "message " + kind;
}

function localDateTimeValue(date = new Date()) {
  const offset = date.getTimezoneOffset();
  const local = new Date(date.getTime() - offset * 60000);
  return local.toISOString().slice(0, 16);
}

function factualTime() {
  const value = $("actionTime").value;
  if (!value) {
    throw new Error("Please enter the action time.");
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    throw new Error("The action time is invalid.");
  }
  return parsed.toISOString();
}

function selectedTaskId() {
  const value = $("task").value;
  if (!value) {
    throw new Error("Please choose a task.");
  }
  return value;
}

function renderSnapshot(value) {
  snapshot = value || {};
  const select = $("task");
  const previous = select.value;
  select.textContent = "";

  const tasks = snapshot.tasks || [];
  for (const task of tasks) {
    const option = document.createElement("option");
    option.value = task.id;
    option.textContent = task.summary || task.id;
    select.appendChild(option);
  }

  const preferred = snapshot.current_task_id || previous;
  if (preferred && tasks.some((task) => task.id === preferred)) {
    select.value = preferred;
  }

  const current = snapshot.current_task_id;
  const paused = new Set(snapshot.paused_task_ids || []);
  if (current) {
    const task = tasks.find((item) => item.id === current);
    $("taskState").textContent = "Working: " + (task?.summary || current);
  } else if (select.value && paused.has(select.value)) {
    $("taskState").textContent = "Paused";
  } else {
    $("taskState").textContent = tasks.length ? "Ready" : "No active VTODOs";
  }

  $("wpState").textContent =
    snapshot.wordpress_pending > 0
      ? `Pending WordPress records: ${snapshot.wordpress_pending}`
      : "WordPress outbox: clear";
}

async function refresh() {
  showMessage("");
  const value = await nativeRequest({ type: "snapshot" });
  renderSnapshot(value);
}

async function runAction(action) {
  showMessage("");
  const taskId = selectedTaskId();
  const at = factualTime();
  const result = await nativeRequest({
    type: "action",
    action,
    task_id: taskId,
    at,
  });
  showMessage(result?.message || `${action} recorded.`, "ok");
  await refresh();
}

async function saveNote() {
  const text = $("note").value.trim();
  if (!text) {
    throw new Error("Write something before adding a WordPress record.");
  }
  const result = await nativeRequest({
    type: "log",
    text,
    task_id: $("task").value || "",
    at: factualTime(),
    calendar_link: $("calendarLink").checked,
  });
  $("note").value = "";
  showMessage(result?.message || "WordPress record saved.", "ok");
  await refresh();
}

function bufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunk = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

async function uploadFiles() {
  const files = Array.from($("files").files || []);
  if (!files.length) {
    throw new Error("Choose at least one file or image.");
  }
  const taskId = $("task").value || "";
  for (const file of files) {
    showMessage(`Uploading ${file.name}…`);
    const data = bufferToBase64(await file.arrayBuffer());
    await nativeRequest({
      type: "attachment",
      name: file.name,
      mime_type: file.type || "application/octet-stream",
      data_base64: data,
      task_id: taskId,
      at: factualTime(),
      calendar_link: $("calendarLink").checked,
      calendar_attachment_link: $("attachmentLink").checked,
    });
  }
  $("files").value = "";
  showMessage(`${files.length} attachment(s) saved to WordPress.`, "ok");
  await refresh();
}

async function syncWordPress() {
  const result = await nativeRequest({ type: "sync_wordpress" });
  showMessage(
    `WordPress sync: ${result.sent || 0} sent, ${result.pending || 0} pending.`,
    result.failed ? "error" : "ok"
  );
  await refresh();
}

async function loadPreferences() {
  const prefs = await messenger.storage.local.get({
    calendarLink: true,
    attachmentLink: false,
  });
  $("calendarLink").checked = prefs.calendarLink !== false;
  $("attachmentLink").checked = prefs.attachmentLink === true;
}

function bind() {
  $("actionTime").value = localDateTimeValue();

  for (const button of document.querySelectorAll("[data-action]")) {
    button.addEventListener("click", () => {
      runAction(button.dataset.action).catch((error) =>
        showMessage(error.message, "error")
      );
    });
  }

  $("refresh").addEventListener("click", () =>
    refresh().catch((error) => showMessage(error.message, "error"))
  );
  $("saveNote").addEventListener("click", () =>
    saveNote().catch((error) => showMessage(error.message, "error"))
  );
  $("upload").addEventListener("click", () =>
    uploadFiles().catch((error) => showMessage(error.message, "error"))
  );
  $("syncWp").addEventListener("click", () =>
    syncWordPress().catch((error) => showMessage(error.message, "error"))
  );

  $("calendarLink").addEventListener("change", () =>
    messenger.storage.local.set({ calendarLink: $("calendarLink").checked })
  );
  $("attachmentLink").addEventListener("change", () =>
    messenger.storage.local.set({ attachmentLink: $("attachmentLink").checked })
  );

  $("task").addEventListener("change", () => renderSnapshot(snapshot));
}

(async () => {
  try {
    bind();
    await loadPreferences();
    await nativeRequest({ type: "ping" });
    await refresh();
  } catch (error) {
    showMessage(error.message, "error");
  }
})();
