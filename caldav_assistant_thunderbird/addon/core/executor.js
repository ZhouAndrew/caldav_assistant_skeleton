"use strict";

(() => {
  function errorText(error) {
    return String(error?.message || error || "Unknown error");
  }

  function toLocalInput(value = new Date()) {
    const pad = number => String(number).padStart(2, "0");
    return [
      value.getFullYear(),
      pad(value.getMonth() + 1),
      pad(value.getDate()),
    ].join("-") +
      "T" +
      [pad(value.getHours()), pad(value.getMinutes()), pad(value.getSeconds())].join(":");
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
            calendarId: task.calendarId,
            calendarName: task.calendarName,
            title: task.title,
            recurrenceId: String(task.recurrenceId || ""),
            beforeStatus: task.status || "",
            beforePaused: Boolean(task.paused),
            beforePercentComplete: Number(task.percentComplete || 0),
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

  async function isCurrentTask(task) {
    const currentWorkId = await AssistantStorage.getCurrentWorkId();
    return Boolean(
      currentWorkId &&
      currentWorkId === AssistantStorage.makeWorkTaskId(task)
    );
  }

  function taskSnapshot(task) {
    return {
      status: task.status || null,
      paused: Boolean(task.paused),
      percentComplete: Number(task.percentComplete || 0),
    };
  }

  function switchRestoreSnapshot(runtime, task) {
    const saved = runtime?.taskBeforeStart;
    if (saved && typeof saved === "object") {
      return {
        status: saved.status || null,
        paused: Boolean(saved.paused),
        percentComplete: Number(saved.percentComplete || 0),
      };
    }

    // Compatibility for a work session that was started by an older add-on build.
    // The old runtime did not persist the pre-start Task snapshot, so the safest
    // incomplete state is NEEDS-ACTION while preserving existing progress.
    return {
      status: "NEEDS-ACTION",
      paused: false,
      percentComplete: Math.min(99, Math.max(0, Number(task?.percentComplete || 0))),
    };
  }

  async function readBackTask(task, receipt, expected = {}) {
    const stored = await browser.ThunderbirdCalDAV.getTask(
      task.calendarId,
      task.id,
      task.recurrenceId || ""
    );
    for (const [key, value] of Object.entries(expected)) {
      if (stored[key] !== value) {
        throw new Error(
          `Task read-back mismatch for ${key}: expected ${String(value)}, got ${String(stored[key])}`
        );
      }
    }
    step(receipt, "CalDAV", "read-back task", true, {
      uid: stored.id,
      calendar: stored.calendarName,
      status: stored.status,
      paused: Boolean(stored.paused),
      percentComplete: stored.percentComplete,
    });
    return stored;
  }

  async function updateAndVerifyTask(task, changes, expected, receipt) {
    await browser.ThunderbirdCalDAV.updateTask(
      task.calendarId,
      task.id,
      changes,
      task.recurrenceId || ""
    );
    step(receipt, "CalDAV", "write task", true, {
      uid: task.id,
      calendar: task.calendarName,
      changes,
    });
    return readBackTask(task, receipt, expected);
  }

  async function restoreTask(task, snapshot, receipt) {
    try {
      await browser.ThunderbirdCalDAV.updateTask(
        task.calendarId,
        task.id,
        snapshot,
        task.recurrenceId || ""
      );
      const stored = await browser.ThunderbirdCalDAV.getTask(
        task.calendarId,
        task.id,
        task.recurrenceId || ""
      );
      const expectedStatus = snapshot.status || "";
      if (
        stored.status !== expectedStatus ||
        Boolean(stored.paused) !== Boolean(snapshot.paused) ||
        Number(stored.percentComplete || 0) !== Number(snapshot.percentComplete || 0)
      ) {
        throw new Error("Task rollback read-back mismatch.");
      }
      step(receipt, "Rollback", "restore task state", true, {
        uid: task.id,
        status: stored.status,
        paused: Boolean(stored.paused),
        percentComplete: stored.percentComplete,
      });
      return true;
    } catch (error) {
      step(receipt, "Rollback", "restore task state", false, {
        uid: task.id,
        message: errorText(error),
      });
      return false;
    }
  }

  async function createWorkEvent(task, workCalendarId, startedAt, receipt) {
    if (!workCalendarId) {
      throw new Error("No writable Work calendar is configured.");
    }
    const uidPart = globalThis.crypto?.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const workRef = {
      id: `caldav-assistant-work-${uidPart}`,
      calendarId: workCalendarId,
    };

    let created;
    try {
      created = await browser.ThunderbirdCalDAV.createEvent(workCalendarId, {
      id: workRef.id,
      title: `Work · ${task.title || "(untitled task)"}`,
      start: startedAt,
      end: null,
      status: "CONFIRMED",
      categories: ["CalDAV Assistant", "Work"],
      description:
        `CalDAV Assistant work session\nTask UID: ${task.id}\nTask Calendar: ${task.calendarName || task.calendarId}` +
        (task.recurrenceId ? `\nTask Recurrence-ID: ${task.recurrenceId}` : ""),
      taskUid: task.id,
      workSession: true,
      workOpen: true,
    });
      step(receipt, "Work Session", "create VEVENT", true, {
        uid: created.id,
        calendarId: created.calendarId,
        calendar: created.calendarName,
        start: created.start?.icalString || null,
        end: created.end?.icalString || null,
        taskUid: created.taskUid,
        workSession: created.workSession,
        workOpen: created.workOpen,
      });

      const stored = await browser.ThunderbirdCalDAV.getEvent(
        created.calendarId,
        created.id
      );
      if (stored.taskUid !== task.id || !stored.workSession) {
        throw new Error(
          `Work VEVENT read-back lost relation: taskUid=${stored.taskUid || "(empty)"}, workSession=${String(stored.workSession)}`
        );
      }
      if (!stored.workOpen) {
        throw new Error(
          "Work VEVENT read-back lost X-CALDAV-ASSISTANT-WORK-OPEN."
        );
      }
      step(receipt, "Work Session", "read-back VEVENT", true, {
        uid: stored.id,
        open: stored.workOpen,
        providerEnd: stored.end?.icalString || null,
        taskUid: stored.taskUid,
        workSession: stored.workSession,
      });
      return stored;
    } catch (error) {
      await deleteWorkEvent(
        {
          id: created?.id || workRef.id,
          calendarId: created?.calendarId || workRef.calendarId,
        },
        receipt
      );
      throw error;
    }
  }

  async function closeWorkEvent(workEvent, endedAt, receipt) {
    if (!workEvent?.id || !workEvent?.calendarId) return null;
    await browser.ThunderbirdCalDAV.updateEvent(workEvent.calendarId, workEvent.id, {
      end: endedAt,
      workOpen: false,
    });
    step(receipt, "Work Session", "close VEVENT", true, {
      uid: workEvent.id,
      end: endedAt,
    });
    const stored = await browser.ThunderbirdCalDAV.getEvent(
      workEvent.calendarId,
      workEvent.id
    );
    if (!stored.end || stored.workOpen) {
      throw new Error(
        `Work VEVENT close read-back mismatch: DTEND=${stored.end?.icalString || "(missing)"}, workOpen=${String(stored.workOpen)}`
      );
    }
    step(receipt, "Work Session", "read-back closed VEVENT", true, {
      uid: stored.id,
      end: stored.end?.icalString || null,
      workOpen: stored.workOpen,
    });
    return stored;
  }

  async function reopenWorkEvent(workEvent, receipt) {
    if (!workEvent?.id || !workEvent?.calendarId) return true;
    try {
      await browser.ThunderbirdCalDAV.updateEvent(workEvent.calendarId, workEvent.id, {
        end: null,
        workOpen: true,
      });
      const stored = await browser.ThunderbirdCalDAV.getEvent(
        workEvent.calendarId,
        workEvent.id
      );
      if (!stored.workOpen) {
        throw new Error("Rollback read-back did not restore Work-open marker.");
      }
      step(receipt, "Rollback", "reopen VEVENT", true, {
        uid: stored.id,
        providerEnd: stored.end?.icalString || null,
        workOpen: stored.workOpen,
      });
      return true;
    } catch (error) {
      step(receipt, "Rollback", "reopen VEVENT", false, {
        uid: workEvent.id,
        message: errorText(error),
      });
      return false;
    }
  }

  async function deleteWorkEvent(workEvent, receipt) {
    if (!workEvent?.id || !workEvent?.calendarId) return true;
    let deleteError = null;
    try {
      await browser.ThunderbirdCalDAV.deleteEvent(workEvent.calendarId, workEvent.id);
    } catch (error) {
      deleteError = error;
    }

    try {
      await browser.ThunderbirdCalDAV.getEvent(workEvent.calendarId, workEvent.id);
      step(receipt, "Rollback", "delete created VEVENT", false, {
        uid: workEvent.id,
        message: deleteError
          ? errorText(deleteError)
          : "Deleted Work VEVENT is still readable.",
      });
      return false;
    } catch (_notFound) {
      step(receipt, "Rollback", "delete created VEVENT", true, {
        uid: workEvent.id,
        note: deleteError ? "VEVENT was already absent." : "Deletion verified by read-back absence.",
      });
      return true;
    }
  }

  async function restoreRuntime(runtime, receipt) {
    try {
      await AssistantStorage.setRuntime(runtime);
      step(receipt, "Rollback", "restore runtime state", true, {
        state: runtime.state,
        taskUid: runtime.currentTask?.id || null,
        workEventUid: runtime.currentWorkEvent?.id || null,
      });
      return true;
    } catch (error) {
      step(receipt, "Rollback", "restore runtime state", false, {
        message: errorText(error),
      });
      return false;
    }
  }

  async function logClosedWorkSession(task, closedEvent, receipt) {
    if (!closedEvent) {
      step(receipt, "WordPress", "not invoked", true, {
        note: "No newly closed Work Session needs a WordPress append.",
      });
      return;
    }
    if (!globalThis.AssistantDailyLog?.recordClosedWorkSession) {
      step(receipt, "WordPress", "not invoked", true, {
        note: "Daily log service is unavailable in this execution context.",
      });
      return;
    }
    try {
      await AssistantDailyLog.recordClosedWorkSession(task, closedEvent, receipt);
    } catch (error) {
      step(receipt, "WordPress", "daily log handoff failed", false, {
        message: errorText(error),
        note: "Task/CalDAV state remains committed; WordPress is not the task source of truth.",
      });
    }
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

  async function start(task, workCalendarId) {
    return runAction("start", task, async receipt => {
      ensureMutableTask(task);
      const runtime = await AssistantStorage.getRuntime();
      const currentWorkId = await AssistantStorage.getCurrentWorkId();
      if (currentWorkId) {
        throw new Error("Another task is already active.");
      }

      const beforeTask = taskSnapshot(task);
      let taskWritten = false;
      let workEvent = null;

      try {
        taskWritten = true;
        await updateAndVerifyTask(
          task,
          {status: "IN-PROCESS", paused: false},
          {status: "IN-PROCESS", paused: false},
          receipt
        );

        workEvent = await createWorkEvent(task, workCalendarId, toLocalInput(), receipt);

        await AssistantStorage.setRuntime({
          state: "working",
          currentTask: {
            id: task.id,
            calendarId: task.calendarId,
            title: task.title,
            recurrenceId: String(task.recurrenceId || ""),
          },
          currentWorkEvent: {
            id: workEvent.id,
            calendarId: workEvent.calendarId,
          },
          segmentStartedAtMs: Date.now(),
          accumulatedMs: 0,
          taskBeforeStart: beforeTask,
        });
        step(receipt, "Runtime", "set current task", true, {
          state: "working",
          taskUid: task.id,
          workEventUid: workEvent.id,
        });
      } catch (error) {
        if (workEvent) await deleteWorkEvent(workEvent, receipt);
        if (taskWritten) await restoreTask(task, beforeTask, receipt);
        await restoreRuntime(runtime, receipt);
        throw error;
      }
    });
  }

  async function pause(task) {
    return runAction("pause", task, async receipt => {
      ensureMutableTask(task);
      const runtime = await AssistantStorage.getRuntime();
      if (runtime.state !== "working" || !(await isCurrentTask(task))) {
        throw new Error("The selected task is not the currently working task.");
      }

      const beforeTask = taskSnapshot(task);
      let eventClosed = false;
      let closedEvent = null;
      let taskWritten = false;

      try {
        eventClosed = true;
        closedEvent = await closeWorkEvent(runtime.currentWorkEvent, toLocalInput(), receipt);

        taskWritten = true;
        await updateAndVerifyTask(
          task,
          {status: "IN-PROCESS", paused: true},
          {status: "IN-PROCESS", paused: true},
          receipt
        );

        const elapsed = runtime.segmentStartedAtMs
          ? Math.max(0, Date.now() - runtime.segmentStartedAtMs)
          : 0;
        await AssistantStorage.setRuntime({
          ...runtime,
          state: "paused",
          currentWorkEvent: null,
          segmentStartedAtMs: null,
          accumulatedMs: Number(runtime.accumulatedMs || 0) + elapsed,
        });
        step(receipt, "Runtime", "set paused state", true, {
          accumulatedMs: Number(runtime.accumulatedMs || 0) + elapsed,
        });
        await logClosedWorkSession(task, closedEvent, receipt);
      } catch (error) {
        if (taskWritten) await restoreTask(task, beforeTask, receipt);
        if (eventClosed) await reopenWorkEvent(runtime.currentWorkEvent, receipt);
        await restoreRuntime(runtime, receipt);
        throw error;
      }
    });
  }

  async function switchAway(task) {
    return runAction("switch-away", task, async receipt => {
      ensureMutableTask(task);
      const runtime = await AssistantStorage.getRuntime();
      if (!(await isCurrentTask(task)) || !["working", "paused"].includes(runtime.state)) {
        throw new Error("The selected task is not the current task.");
      }

      const beforeTask = taskSnapshot(task);
      const restoreTo = switchRestoreSnapshot(runtime, task);
      let eventClosed = false;
      let closedEvent = null;
      let taskWritten = false;

      try {
        if (runtime.state === "working" && runtime.currentWorkEvent) {
          eventClosed = true;
          closedEvent = await closeWorkEvent(runtime.currentWorkEvent, toLocalInput(), receipt);
        }

        taskWritten = true;
        await updateAndVerifyTask(
          task,
          restoreTo,
          {
            status: restoreTo.status || "",
            paused: Boolean(restoreTo.paused),
            percentComplete: Number(restoreTo.percentComplete || 0),
          },
          receipt
        );

        await AssistantStorage.clearRuntime();
        step(receipt, "Runtime", "release current task", true, {
          state: "idle",
          taskUid: task.id,
          restoredStatus: restoreTo.status || "",
          restoredPaused: Boolean(restoreTo.paused),
          restoredPercentComplete: Number(restoreTo.percentComplete || 0),
        });
        await logClosedWorkSession(task, closedEvent, receipt);
      } catch (error) {
        if (taskWritten) await restoreTask(task, beforeTask, receipt);
        if (eventClosed) await reopenWorkEvent(runtime.currentWorkEvent, receipt);
        await restoreRuntime(runtime, receipt);
        throw error;
      }
    });
  }

  // Compatibility alias for callers from 0.3.11-0.3.14. New UI code uses the
  // semantically explicit switchAway() name.
  const putAside = switchAway;

  async function resume(task, workCalendarId) {
    return runAction("resume", task, async receipt => {
      ensureMutableTask(task);
      const runtime = await AssistantStorage.getRuntime();
      if (runtime.state !== "paused" || !(await isCurrentTask(task))) {
        throw new Error("The selected task is not paused.");
      }

      const beforeTask = taskSnapshot(task);
      let taskWritten = false;
      let workEvent = null;

      try {
        taskWritten = true;
        await updateAndVerifyTask(
          task,
          {status: "IN-PROCESS", paused: false},
          {status: "IN-PROCESS", paused: false},
          receipt
        );

        workEvent = await createWorkEvent(task, workCalendarId, toLocalInput(), receipt);

        await AssistantStorage.setRuntime({
          ...runtime,
          state: "working",
          currentWorkEvent: {
            id: workEvent.id,
            calendarId: workEvent.calendarId,
          },
          segmentStartedAtMs: Date.now(),
        });
        step(receipt, "Runtime", "set working state", true, {
          workEventUid: workEvent.id,
        });
      } catch (error) {
        if (workEvent) await deleteWorkEvent(workEvent, receipt);
        if (taskWritten) await restoreTask(task, beforeTask, receipt);
        await restoreRuntime(runtime, receipt);
        throw error;
      }
    });
  }

  async function finish(task, status) {
    const action = status === "COMPLETED" ? "complete" : "cancel";

    return runAction(action, task, async receipt => {
      ensureMutableTask(task);
      const runtime = await AssistantStorage.getRuntime();
      if (!(await isCurrentTask(task)) || !["working", "paused"].includes(runtime.state)) {
        throw new Error("The selected task is not the current task.");
      }

      const beforeTask = taskSnapshot(task);
      let eventClosed = false;
      let closedEvent = null;
      let taskWritten = false;

      try {
        if (runtime.state === "working" && runtime.currentWorkEvent) {
          eventClosed = true;
          closedEvent = await closeWorkEvent(runtime.currentWorkEvent, toLocalInput(), receipt);
        }

        const changes =
          status === "COMPLETED"
            ? {status: "COMPLETED", paused: false, percentComplete: 100}
            : {status: "CANCELLED", paused: false};

        taskWritten = true;
        await updateAndVerifyTask(task, changes, {status, paused: false}, receipt);

        await AssistantStorage.clearRuntime();
        step(receipt, "Runtime", "clear current task", true, {state: "idle"});
        await logClosedWorkSession(task, closedEvent, receipt);
      } catch (error) {
        if (taskWritten) await restoreTask(task, beforeTask, receipt);
        if (eventClosed) await reopenWorkEvent(runtime.currentWorkEvent, receipt);
        await restoreRuntime(runtime, receipt);
        throw error;
      }
    });
  }

  globalThis.AssistantExecutor = Object.freeze({
    start,
    pause,
    switchAway,
    putAside,
    resume,
    complete: task => finish(task, "COMPLETED"),
    cancel: task => finish(task, "CANCELLED"),
    toLocalInput,
  });
})();
