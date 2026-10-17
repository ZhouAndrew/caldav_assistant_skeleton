"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const {t, rpc, statusText, formatElapsed, showMessage} = window.AppUi;
  const params = new URLSearchParams(location.search);
  const taskId = params.get("id") || "";

  const title = document.getElementById("title");
  const status = document.getElementById("status");
  const progress = document.getElementById("progress");
  const elapsed = document.getElementById("elapsed");
  const description = document.getElementById("description");
  const actions = document.getElementById("actions");
  const errorBox = document.getElementById("error");
  const noticeBox = document.getElementById("notice");

  const actionKeys = {
    start: "actionStart",
    stop: "actionStop",
    complete: "actionComplete",
    cancel: "actionCancel",
  };

  let active = false;
  let baseElapsed = 0;
  let baseAt = performance.now();
  let timer = null;
  let commandRunning = false;

  function renderElapsed() {
    const value = active
      ? baseElapsed + Math.max(0, performance.now() - baseAt)
      : baseElapsed;
    elapsed.textContent = formatElapsed(value);
  }

  function restartTimer() {
    clearInterval(timer);
    timer = null;
    renderElapsed();
    if (active) {
      timer = setInterval(renderElapsed, 1000);
    }
  }

  function renderActions(list) {
    actions.replaceChildren();
    for (const intent of list) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = t(actionKeys[intent] || intent);
      button.dataset.intent = intent;
      if (intent === "start" || intent === "complete") {
        button.classList.add("primary");
      }
      button.disabled = commandRunning;
      button.addEventListener("click", () => runCommand(intent));
      actions.appendChild(button);
    }
  }

  function renderView(view) {
    title.textContent = view.title || t("taskUntitled");
    status.textContent = statusText(view.status);
    progress.textContent = String(view.percentComplete) + "%";
    description.textContent = view.userDescription || "";

    baseElapsed = Number(view.elapsedMs || 0);
    baseAt = performance.now();
    active = Array.isArray(view.actions) && view.actions.includes("stop");
    restartTimer();

    showMessage(
      errorBox,
      view.errorKey ? t(view.errorKey) : "",
      "error"
    );
    showMessage(
      noticeBox,
      view.noticeKey ? t(view.noticeKey) : "",
      "info"
    );
    renderActions(view.actions || []);
  }

  async function refresh() {
    if (!taskId) {
      showMessage(errorBox, t("taskLoadFailed"), "error");
      return;
    }

    const result = await rpc({type: "task.read", taskId});
    if (!result?.ok) {
      showMessage(
        errorBox,
        result?.error?.message || t("taskLoadFailed"),
        "error"
      );
      actions.replaceChildren();
      return;
    }
    renderView(result.view);
  }

  async function runCommand(intent) {
    if (commandRunning) return;
    commandRunning = true;
    for (const button of actions.querySelectorAll("button")) {
      button.disabled = true;
    }
    showMessage(errorBox, "");

    try {
      const response = await rpc({
        type: "task.command",
        taskId,
        intent,
      });
      if (!response?.ok) {
        showMessage(
          errorBox,
          response?.error?.message || t("commandFailed"),
          "error"
        );
        return;
      }
      if (!response.result?.ok) {
        showMessage(
          errorBox,
          t("commandFailed") + " " + String(response.result?.message || ""),
          "error"
        );
      }
    } catch (error) {
      showMessage(errorBox, String(error?.message || error), "error");
    } finally {
      commandRunning = false;
      await refresh();
    }
  }

  void refresh();
});
