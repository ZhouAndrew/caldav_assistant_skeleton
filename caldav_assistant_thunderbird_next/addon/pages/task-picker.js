"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const {t, rpc, statusText, formatDateTime, showMessage} = window.AppUi;
  const search = document.getElementById("search");
  const filter = document.getElementById("filter");
  const calendar = document.getElementById("calendar");
  const refresh = document.getElementById("refresh");
  const list = document.getElementById("task-list");
  const empty = document.getElementById("empty");
  const message = document.getElementById("message");

  let searchTimer = null;
  let generation = 0;

  async function loadCalendars() {
    const result = await rpc({type: "calendars.list"});
    if (!result?.ok) {
      showMessage(
        message,
        result?.error?.message || t("calendarLoadFailed"),
        "error"
      );
      return;
    }

    for (const item of result.calendars) {
      if (item.disabled) continue;
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.name || item.id;
      calendar.appendChild(option);
    }
  }

  function queryOptions() {
    return {
      filter: filter.value,
      search: search.value,
      calendarIds: calendar.value ? [calendar.value] : [],
    };
  }

  function renderItems(items) {
    list.replaceChildren();
    empty.hidden = items.length !== 0;

    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "task-row";

      const title = document.createElement("strong");
      title.textContent = item.title || t("taskUntitled");

      const meta = document.createElement("span");
      meta.className = "meta";

      const status = document.createElement("span");
      status.textContent =
        statusText(item.status) + " · " + String(item.percentComplete) + "%";
      meta.appendChild(status);

      if (item.calendarName) {
        const cal = document.createElement("span");
        cal.textContent = item.calendarName;
        meta.appendChild(cal);
      }

      if (item.due) {
        const due = document.createElement("span");
        due.textContent = t("due") + ": " + formatDateTime(item.due);
        meta.appendChild(due);
      }

      button.append(title, meta);
      button.addEventListener("click", () => {
        location.href =
          "task.html?id=" + encodeURIComponent(item.taskId);
      });
      list.appendChild(button);
    }
  }

  async function runQuery() {
    const myGeneration = ++generation;
    refresh.disabled = true;

    try {
      const result = await rpc({
        type: "tasks.query",
        options: queryOptions(),
      });
      if (myGeneration !== generation) return;

      if (!result?.ok) {
        renderItems([]);
        showMessage(
          message,
          result?.error?.message || t("taskLoadFailed"),
          "error"
        );
        return;
      }

      renderItems(result.view.items || []);
      if (!result.complete) {
        showMessage(message, t("queryIncomplete"), "warning");
      } else {
        showMessage(message, "");
      }
    } catch (error) {
      if (myGeneration !== generation) return;
      renderItems([]);
      showMessage(message, String(error?.message || error), "error");
    } finally {
      if (myGeneration === generation) refresh.disabled = false;
    }
  }

  refresh.addEventListener("click", runQuery);
  filter.addEventListener("change", runQuery);
  calendar.addEventListener("change", runQuery);
  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runQuery, 150);
  });

  void loadCalendars().then(runQuery);
});
