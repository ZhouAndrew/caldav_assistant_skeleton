(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.CalDAVAssistantRefresh = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function errorText(error) {
    if (error == null) return "Unknown error";
    if (typeof error === "string") return error;
    const name = String(error.name || "").trim();
    const message = String(error.message || error).trim();
    if (name && message && !message.startsWith(name + ":")) return name + ": " + message;
    return message || name || "Unknown error";
  }

  function withTimeout(promise, timeoutMs, label) {
    const ms = Math.max(1, Number(timeoutMs || 1));
    let timer = null;
    return Promise.race([
      Promise.resolve(promise),
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(`${label || "Operation"} timed out after ${ms} ms`)),
          ms
        );
      }),
    ]).finally(() => {
      if (timer) clearTimeout(timer);
    });
  }

  function actionableTasks(tasks) {
    return (Array.isArray(tasks) ? tasks : []).filter(task => {
      const status = String(task?.status || "").toUpperCase();
      return !task?.completed && status !== "COMPLETED" && status !== "CANCELLED";
    });
  }

  async function readLocalSnapshot(messenger, options = {}) {
    const bridge = messenger?.assistantCalendar;
    if (!bridge) throw new Error("Thunderbird local Calendar/Tasks bridge is unavailable.");

    const timeoutMs = Math.max(250, Number(options.timeoutMs || 4000));

    if (typeof bridge.refreshSnapshot === "function") {
      let value;
      try {
        value = await withTimeout(
          Promise.resolve().then(() => bridge.refreshSnapshot()),
          timeoutMs,
          "Thunderbird local refresh"
        );
      } catch (error) {
        const wrapped = new Error("Thunderbird local refresh call failed: " + errorText(error));
        wrapped.cause = error;
        throw wrapped;
      }

      if (!value || value.ok === false) {
        const detail = value?.error || "Thunderbird local refresh returned no usable data";
        const wrapped = new Error("Thunderbird local refresh failed: " + detail);
        wrapped.diagnostics = value?.diagnostics || null;
        throw wrapped;
      }

      return {
        tasks: actionableTasks(value.tasks),
        work: value.work || {},
        diagnostics: value.diagnostics || {},
        source: value.source || "thunderbird-calendar-cache",
      };
    }

    if (typeof bridge.listTasks !== "function" || typeof bridge.workState !== "function") {
      throw new Error("Thunderbird local refresh API is incomplete.");
    }

    const [tasks, work] = await withTimeout(
      Promise.all([bridge.listTasks(), bridge.workState()]),
      timeoutMs,
      "Thunderbird legacy local refresh"
    );
    return {
      tasks: actionableTasks(tasks),
      work: work || {},
      diagnostics: {mode: "legacy-two-call"},
      source: "thunderbird-calendar-cache-legacy",
    };
  }

  async function resilientRefresh(options) {
    const messenger = options?.messenger;
    const fallback = options?.fallback;
    const timeoutMs = options?.timeoutMs || 4000;
    if (typeof fallback !== "function") throw new Error("A refresh fallback function is required.");

    const started = Date.now();
    try {
      const data = await readLocalSnapshot(messenger, {timeoutMs});
      return {
        ok: true,
        source: "local",
        data,
        localError: null,
        fallbackError: null,
        elapsedMs: Date.now() - started,
      };
    } catch (localError) {
      try {
        const data = await fallback();
        return {
          ok: true,
          source: "fallback",
          data,
          localError: errorText(localError),
          localDiagnostics: localError?.diagnostics || null,
          fallbackError: null,
          elapsedMs: Date.now() - started,
        };
      } catch (fallbackError) {
        const error = new Error(
          "Refresh failed. Thunderbird local: " +
            errorText(localError) +
            "; CalDAV fallback: " +
            errorText(fallbackError)
        );
        error.localError = errorText(localError);
        error.localDiagnostics = localError?.diagnostics || null;
        error.fallbackError = errorText(fallbackError);
        error.elapsedMs = Date.now() - started;
        throw error;
      }
    }
  }

  return {
    errorText,
    withTimeout,
    actionableTasks,
    readLocalSnapshot,
    resilientRefresh,
  };
});
