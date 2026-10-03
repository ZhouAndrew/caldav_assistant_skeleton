"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const {t, rpc, formatDateTime, showMessage} = window.AppUi;
  const dateInput = document.getElementById("date");
  const refresh = document.getElementById("refresh");
  const sessions = document.getElementById("sessions");
  const empty = document.getElementById("empty");
  const message = document.getElementById("message");

  function localDateKey() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return [year, month, day].join("-");
  }

  function resultText(result) {
    if (result === "stop") return t("resultStop");
    if (result === "complete") return t("resultComplete");
    if (result === "cancel") return t("resultCancel");
    return t("sessionOpen");
  }

  function renderRows(rows) {
    sessions.replaceChildren();
    empty.hidden = rows.length !== 0;

    for (const row of rows) {
      const card = document.createElement("article");
      card.className = "session-row";

      const title = document.createElement("strong");
      title.textContent = row.title || t("taskUntitled");

      const meta = document.createElement("div");
      meta.className = "meta";

      const time = document.createElement("span");
      time.textContent =
        formatDateTime(row.start) +
        (row.end ? " → " + formatDateTime(row.end) : "");

      const result = document.createElement("span");
      result.textContent = resultText(row.result);

      const open = document.createElement("a");
      open.href = "task.html?id=" + encodeURIComponent(row.taskId);
      open.textContent = t("actionOpenTask");

      meta.append(time, result, open);
      card.append(title, meta);
      sessions.appendChild(card);
    }
  }

  async function load() {
    refresh.disabled = true;
    try {
      const result = await rpc({
        type: "today.read",
        date: dateInput.value,
      });
      if (!result?.ok) {
        renderRows([]);
        showMessage(
          message,
          result?.error?.message || t("taskLoadFailed"),
          "error"
        );
        return;
      }

      renderRows(result.view.rows || []);
      const warnings = result.view.warnings || [];
      if (!result.complete) {
        showMessage(message, t("queryIncomplete"), "warning");
      } else if (warnings.length) {
        showMessage(message, t(warnings[0].key), "warning");
      } else {
        showMessage(message, "");
      }
    } catch (error) {
      renderRows([]);
      showMessage(message, String(error?.message || error), "error");
    } finally {
      refresh.disabled = false;
    }
  }

  dateInput.value = localDateKey();
  refresh.addEventListener("click", load);
  dateInput.addEventListener("change", load);
  void load();
});
