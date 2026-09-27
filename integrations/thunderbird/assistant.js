const HOST = "local.caldav_assistant";
const $ = (id) => document.getElementById(id);

function localInputNow() {
  const d = new Date();
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - off).toISOString().slice(0, 16);
}

function isoFromInput() {
  const raw = $("when").value;
  if (!raw) throw new Error("Please enter a time.");
  const value = new Date(raw);
  if (Number.isNaN(value.getTime())) throw new Error("Invalid time.");
  return value.toISOString();
}

function show(message) {
  const box = $("message");
  box.textContent = message;
  box.classList.add("show");
  setTimeout(() => box.classList.remove("show"), 4000);
}

async function host(message) {
  const result = await messenger.runtime.sendNativeMessage(HOST, message);
  if (!result || result.ok === false) {
    throw new Error(result?.error || "Native host did not return a valid response.");
  }
  return result;
}

function selectedTaskId() {
  const value = $("task").value;
  if (!value) throw new Error("Choose a task first.");
  return value;
}

function taskLabel(task, state) {
  const marks = [];
  if (state.current_task_id === task.id) marks.push("▶");
  if ((state.paused_task_ids || []).includes(task.id)) marks.push("⏸");
  if (task.status === "COMPLETED") marks.push("✓");
  if (task.status === "CANCELLED") marks.push("×");
  return (marks.length ? marks.join("") + " " : "") + task.summary;
}

async function refresh() {
  const data = await host({command: "snapshot"});
  const select = $("task");
  const old = select.value;
  select.textContent = "";
  for (const task of data.tasks) {
    const option = document.createElement("option");
    option.value = task.id;
    option.textContent = taskLabel(task, data.state);
    select.appendChild(option);
  }
  if (old && data.tasks.some(t => t.id === old)) select.value = old;
  if (!select.value && data.state.current_task_id) select.value = data.state.current_task_id;
  $("bridge-status").textContent = "Core connected";
  $("task-status").textContent = data.state.current_task_id
    ? "Working: " + (data.tasks.find(t => t.id === data.state.current_task_id)?.summary || data.state.current_task_id)
    : "No active work";
  $("today").textContent = (data.today || []).join("\n") || "No recorded activity today.";
}

async function doAction(action) {
  const taskId = selectedTaskId();
  const response = await host({
    command: "action",
    action,
    task_id: taskId,
    at: isoFromInput(),
    calendar_link: $("calendar-link").checked,
  });
  const wp = response.wordpress;
  show(response.message + (wp?.message ? " · " + wp.message : ""));
  $("when").value = localInputNow();
  await refresh();
}

async function addNote() {
  const text = $("note").value.trim();
  if (!text) throw new Error("Write a note first.");
  const response = await host({
    command: "note",
    task_id: selectedTaskId(),
    text,
    at: isoFromInput(),
    calendar_link: $("calendar-link").checked,
  });
  $("note").value = "";
  show(response.message || "Added to WordPress.");
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => {
      const bytes = new Uint8Array(reader.result);
      let binary = "";
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
      }
      resolve(btoa(binary));
    };
    reader.readAsArrayBuffer(file);
  });
}

async function uploadFiles(files) {
  const area = $("uploads");
  for (const file of files) {
    const row = document.createElement("div");
    row.textContent = "Uploading " + file.name + "…";
    area.appendChild(row);
    try {
      const response = await host({
        command: "attachment",
        task_id: selectedTaskId(),
        filename: file.name,
        mime_type: file.type || "application/octet-stream",
        data_base64: await fileToBase64(file),
        at: isoFromInput(),
        calendar_link: $("calendar-link").checked,
        attachment_link: $("attachment-link").checked,
      });
      row.textContent = "✓ " + file.name + (response.url ? " → " + response.url : " (queued)");
    } catch (error) {
      row.textContent = "✗ " + file.name + ": " + error.message;
    }
  }
}

async function loadSettings() {
  const stored = await messenger.storage.local.get({
    calendarLink: true,
    attachmentLink: false,
  });
  $("calendar-link").checked = stored.calendarLink;
  $("attachment-link").checked = stored.attachmentLink;
}

$("calendar-link").addEventListener("change", () =>
  messenger.storage.local.set({calendarLink: $("calendar-link").checked})
);
$("attachment-link").addEventListener("change", () =>
  messenger.storage.local.set({attachmentLink: $("attachment-link").checked})
);
$("refresh").addEventListener("click", () => refresh().catch(e => show(e.message)));
for (const button of document.querySelectorAll("[data-action]")) {
  button.addEventListener("click", () => doAction(button.dataset.action).catch(e => show(e.message)));
}
$("add-note").addEventListener("click", () => addNote().catch(e => show(e.message)));
$("attachment").addEventListener("change", (event) => {
  uploadFiles([...event.target.files]).catch(e => show(e.message));
  event.target.value = "";
});

$("when").value = localInputNow();
loadSettings()
  .then(refresh)
  .catch(error => {
    $("bridge-status").textContent = "Core unavailable";
    show(error.message);
  });
