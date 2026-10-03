"use strict";

(() => {
  function errorText(error) {
    return String(error?.message || error || "Unknown error");
  }

  function currentWorkIdOf(task) {
    if (!task) return null;
    const instanceKey = String(task.instanceKey || "").trim();
    if (instanceKey) return instanceKey;
    const uid = String(task.id || "").trim();
    return uid || null;
  }

  function newReceipt(action, task) {
    return {
      id: `receipt-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      action,
      success: false,
      startedAt: new Date().toISOString(),
      completedAt: null,
      task: task
        ? {
            id: task.id,
            currentWorkId: currentWorkIdOf(task),
            calendarId: task.calendarId,
            calendarName: task.calendarName,
            title: task.title,
            recurrenceId: String(task.recurrenceId || ""),
            beforeStatus: String(task.status || ""),
          }
        : null,
      steps: [],
      error: null,
    };
  }

  function step(receipt, component, operation, success, details = {}) {
    receipt.steps.push({
      timestamp: new Date().toISOString(),
      component,
      operation,
      success,
      details,
    });
  }

  function ensureSelected(task) {
    if (!task?.id || !task?.calendarId) {
      throw new Error("No task is selected.");
    }
  }

  function ensureMutableTask(task) {
    ensureSelected(task);
    if (task.status === "COMPLETED" || task.status === "CANCELLED") {
      throw new Error("The selected task is already finished.");
    }
  }

  function sameCurrentWorkId(currentWorkId, task) {
    if (!currentWorkId || !task) return false;
    return (
      currentWorkId === currentWorkIdOf(task) ||
      currentWorkId === String(task.id || "")
    );
  }

  async function readTask(task) {
    return browser.ThunderbirdCalDAV.getTask(
      task.calendarId,
      task.id,
      task.recurrenceId || ""
    );
  }

  async function updateAndVerifyTask(task, changes, expected, receipt) {
    await browser.ThunderbirdCalDAV.updateTask(
      task.calendarId,
      task.id,
      changes,
      task.recurrenceId || ""
    );
    step(receipt, "Thunderbird Task", "write", true, {
      id: task.id,
      changes,
    });

    const stored = await readTask(task);
    for (const [key, value] of Object.entries(expected || {})) {
      if (stored[key] !== value) {
        throw new Error(
          `Task read-back mismatch for ${key}: expected ${String(value)}, got ${String(stored[key])}`
        );
      }
    }
    step(receipt, "Thunderbird Task", "read-back", true, {
      id: stored.id,
      status: stored.status,
      percentComplete: Number(stored.percentComplete || 0),
    });
    return stored;
  }

  async function restoreTaskAfterFailedStart(task, before, receipt) {
    const changes = {
      status: String(before?.status || "NEEDS-ACTION"),
    };
    const percent = Number(before?.percentComplete || 0);
    if (percent > 0 && percent < 100) {
      changes.percentComplete = percent;
    }

    try {
      await browser.ThunderbirdCalDAV.updateTask(
        task.calendarId,
        task.id,
        changes,
        task.recurrenceId || ""
      );
      const stored = await readTask(task);
      if (stored.status !== changes.status) {
        throw new Error(
          `Task rollback status mismatch: expected ${changes.status}, got ${stored.status}`
        );
      }
      if (
        "percentComplete" in changes &&
        Number(stored.percentComplete || 0) !== percent
      ) {
        throw new Error(
          `Task rollback progress mismatch: expected ${percent}, got ${Number(stored.percentComplete || 0)}`
        );
      }
      step(receipt, "Rollback", "restore Task after current_work_id failure", true, {
        id: stored.id,
        status: stored.status,
        percentComplete: Number(stored.percentComplete || 0),
      });
      return true;
    } catch (error) {
      step(receipt, "Rollback", "restore Task after current_work_id failure", false, {
        id: task.id,
        message: errorText(error),
      });
      return false;
    }
  }

  async function clearCurrentWorkIdAfterTerminalChange(task, receipt) {
    const currentWorkId = await AssistantStorage.getCurrentWorkId();
    if (!sameCurrentWorkId(currentWorkId, task)) return true;

    try {
      await AssistantStorage.clearCurrentWorkId();
      step(receipt, "Assistant State", "clear current_work_id", true, {
        previous: currentWorkId,
      });
      return true;
    } catch (error) {
      // The Thunderbird Task change is already authoritative. Do not undo a
      // successful Stop/Complete/Cancel because an auxiliary local cache write
      // failed. The next currentTask() call will reconcile it again.
      step(receipt, "Assistant State", "clear current_work_id", false, {
        previous: currentWorkId,
        message: errorText(error),
        note: "Task status is committed in Thunderbird; current_work_id will be reconciled on the next read.",
      });
      receipt.summary =
        "Task status was updated, but local current_work_id cleanup needs reconciliation.";
      return false;
    }
  }

  async function currentTask() {
    const currentWorkId = await AssistantStorage.getCurrentWorkId();
    if (!currentWorkId) return null;

    const tasks = await browser.ThunderbirdCalDAV.listTasks();
    let matches = tasks.filter(task => currentWorkIdOf(task) === currentWorkId);

    // One-time compatibility with 0.3.15 runtime migration, where a legacy
    // record may contain only the VTODO UID.
    if (!matches.length) {
      matches = tasks.filter(task => String(task.id || "") === currentWorkId);
    }

    if (matches.length > 1) {
      const active = matches.filter(task => task.status === "IN-PROCESS");
      if (active.length === 1) matches = active;
    }

    if (matches.length !== 1) {
      await AssistantStorage.clearCurrentWorkId();
      if (matches.length > 1) {
        throw new Error("current_work_id is ambiguous in Thunderbird.");
      }
      return null;
    }

    const task = matches[0];
    if (task.status !== "IN-PROCESS") {
      await AssistantStorage.clearCurrentWorkId();
      return null;
    }

    const normalized = currentWorkIdOf(task);
    if (normalized && normalized !== currentWorkId) {
      await AssistantStorage.setCurrentWorkId(normalized);
    }
    return task;
  }

  async function finalizeReceipt(receipt) {
    receipt.completedAt = new Date().toISOString();
    if (!receipt.summary) {
      receipt.summary = receipt.success
        ? `${receipt.action} completed and verified.`
        : `${receipt.action} did not complete: ${receipt.error || "see steps"}`;
    }
    return AssistantStorage.persistResult(receipt, "workflow");
  }

  async function runAction(action, task, runner) {
    const receipt = newReceipt(action, task);
    try {
      await runner(receipt);
      receipt.success = true;
    } catch (error) {
      receipt.success = false;
      receipt.error = errorText(error);
      step(receipt, "Workflow", "error", false, {message: receipt.error});
    }
    return finalizeReceipt(receipt);
  }

  async function start(task) {
    return runAction("start", task, async receipt => {
      ensureMutableTask(task);

      const existing = await currentTask();
      if (existing) {
        if (currentWorkIdOf(existing) === currentWorkIdOf(task)) {
          throw new Error("This Task is already the current work.");
        }
        throw new Error("Stop the current Task before starting another Task.");
      }

      const storedBefore = await readTask(task);
      ensureMutableTask(storedBefore);
      const nextCurrentWorkId = currentWorkIdOf(storedBefore);
      if (!nextCurrentWorkId) throw new Error("Thunderbird Task has no stable id.");

      // Thunderbird is authoritative for Task state. Commit and verify the
      // standard STATUS first, then publish the single Assistant pointer.
      // This prevents another open Assistant page from seeing a pointer to a
      // Task that is still NEEDS-ACTION and clearing it as stale.
      const started = await updateAndVerifyTask(
        storedBefore,
        {status: "IN-PROCESS"},
        {status: "IN-PROCESS"},
        receipt
      );

      try {
        await AssistantStorage.setCurrentWorkId(currentWorkIdOf(started));
        step(receipt, "Assistant State", "set current_work_id", true, {
          currentWorkId: currentWorkIdOf(started),
        });
      } catch (error) {
        await restoreTaskAfterFailedStart(storedBefore, storedBefore, receipt);
        throw error;
      }
    });
  }

  async function stop(task) {
    return runAction("stop", task, async receipt => {
      ensureMutableTask(task);
      const currentWorkId = await AssistantStorage.getCurrentWorkId();
      if (!sameCurrentWorkId(currentWorkId, task)) {
        throw new Error("The selected Task is not the current work.");
      }

      const storedBefore = await readTask(task);
      ensureMutableTask(storedBefore);

      const changes = {status: "NEEDS-ACTION"};
      const percent = Number(storedBefore.percentComplete || 0);
      if (percent > 0 && percent < 100) {
        // Thunderbird clears PERCENT-COMPLETE when leaving isCompleted state.
        // Preserve the user's standard VTODO progress while changing only STATUS.
        changes.percentComplete = percent;
      }

      const expected = {status: "NEEDS-ACTION"};
      if ("percentComplete" in changes) expected.percentComplete = percent;
      await updateAndVerifyTask(storedBefore, changes, expected, receipt);
      await clearCurrentWorkIdAfterTerminalChange(storedBefore, receipt);
    });
  }

  async function complete(task) {
    return runAction("complete", task, async receipt => {
      ensureSelected(task);
      const storedBefore = await readTask(task);
      if (storedBefore.status === "CANCELLED") {
        throw new Error("A cancelled Task cannot be completed.");
      }
      await updateAndVerifyTask(
        storedBefore,
        {status: "COMPLETED"},
        {status: "COMPLETED", percentComplete: 100},
        receipt
      );
      await clearCurrentWorkIdAfterTerminalChange(storedBefore, receipt);
    });
  }

  async function cancel(task) {
    return runAction("cancel", task, async receipt => {
      ensureSelected(task);
      const storedBefore = await readTask(task);
      if (storedBefore.status === "COMPLETED") {
        throw new Error("A completed Task cannot be cancelled.");
      }
      await updateAndVerifyTask(
        storedBefore,
        {status: "CANCELLED"},
        {status: "CANCELLED"},
        receipt
      );
      await clearCurrentWorkIdAfterTerminalChange(storedBefore, receipt);
    });
  }

  globalThis.AssistantExecutor = Object.freeze({
    currentWorkIdOf,
    currentTask,
    start,
    stop,
    complete,
    cancel,
  });
})();
