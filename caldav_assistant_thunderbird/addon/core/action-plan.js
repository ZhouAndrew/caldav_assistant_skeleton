"use strict";

(() => {
  function reject(action, reason) {
    return Object.freeze({ok: false, action, reason});
  }

  function accept(action, taskChanges, nextCurrentWorkId, historyEffect) {
    return Object.freeze({
      ok: true,
      action,
      taskChanges: Object.freeze({...taskChanges}),
      nextCurrentWorkId,
      historyEffect,
    });
  }

  function planWorkAction(
    action,
    currentWorkId,
    task,
    restoreSnapshot = null
  ) {
    if (!task?.workTaskId) {
      throw new Error("Action plan requires a WorkTaskId.");
    }

    if (task.status === "COMPLETED" || task.status === "CANCELLED") {
      return reject(action, "finished");
    }

    const current = currentWorkId === task.workTaskId;

    switch (action) {
      case "start":
        if (currentWorkId !== null) {
          return reject(action, "current-work-exists");
        }
        return accept(
          action,
          {status: "IN-PROCESS", paused: false},
          task.workTaskId,
          "open"
        );

      case "stop":
        if (!current) return reject(action, "not-current");
        if (!restoreSnapshot) return reject(action, "restore-required");
        return accept(
          action,
          {
            status: restoreSnapshot.status,
            paused: false,
            percentComplete: Number(restoreSnapshot.percentComplete || 0),
          },
          null,
          "close"
        );

      case "complete":
        if (!current) return reject(action, "not-current");
        return accept(
          action,
          {status: "COMPLETED", paused: false, percentComplete: 100},
          null,
          "close"
        );

      case "cancel":
        if (!current) return reject(action, "not-current");
        return accept(
          action,
          {status: "CANCELLED", paused: false},
          null,
          "close"
        );

      default:
        throw new Error("Unknown workflow action: " + String(action));
    }
  }

  globalThis.AssistantActionPlan = Object.freeze({
    planWorkAction,
  });
})();
