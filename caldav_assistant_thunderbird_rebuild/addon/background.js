"use strict";

(() => {
  const SPACE_NAME = "caldav_assistant";
  const core = globalThis.CalDAVAssistantCore;
  if (!core) throw new Error("CalDAVAssistantCore bundle is unavailable.");

  const taskPort = globalThis.RebuildTaskPort;
  const storage = globalThis.RebuildStorage;
  const legacyStore = globalThis.RebuildLegacyStore;

  const currentWork = Object.freeze({
    get: () => storage.getCurrentWorkId(),
    set: async value => {
      await storage.setCurrentWorkId(value);
    },
  });

  const workflow = core.createTaskWorkflowService({
    tasks: taskPort,
    currentWork,
    now: () => new Date().toISOString(),
    newSessionId: () =>
      globalThis.crypto?.randomUUID?.() ||
      "session-" + Date.now() + "-" + Math.random().toString(16).slice(2),
    staleWriteRetries: 1,
  });

  let state = Object.freeze({
    migration: null,
    reconciliation: null,
    spaceId: null,
    startupError: null,
  });

  async function ensureSpace() {
    if (!browser.spaces) return null;
    const spaces = await browser.spaces.query({isSelfOwned: true});
    let space = spaces.find(item => item.name === SPACE_NAME) || spaces[0] || null;

    if (space) {
      await browser.spaces.update(
        space.id,
        "workspace.html",
        {title: "CalDAV Assistant"}
      );
      return space.id;
    }

    space = await browser.spaces.create(
      SPACE_NAME,
      "workspace.html",
      {title: "CalDAV Assistant"}
    );
    return space.id;
  }

  async function initialize() {
    try {
      await storage.ensureSettings();

      const migration = await core.migrateLegacyState({
        tasks: taskPort,
        store: legacyStore,
        newSessionId: () =>
          globalThis.crypto?.randomUUID?.() ||
          "migration-" + Date.now() + "-" + Math.random().toString(16).slice(2),
        staleWriteRetries: 1,
      });

      let reconciliation = null;
      if (migration.ok) {
        reconciliation = await core.reconcileCurrentWork(taskPort, currentWork);
      }

      let spaceId = null;
      try {
        spaceId = await ensureSpace();
      } catch (error) {
        console.error("[CalDAV Assistant] Space setup failed", error);
      }

      state = Object.freeze({
        migration,
        reconciliation,
        spaceId,
        startupError: null,
      });
      return state;
    } catch (error) {
      state = Object.freeze({
        migration: null,
        reconciliation: null,
        spaceId: null,
        startupError: String(error?.message || error),
      });
      return state;
    }
  }

  let readyPromise = initialize();

  function blockedForWorkflow() {
    if (state.startupError) return true;
    if (state.migration && state.migration.ok === false) return true;
    if (state.reconciliation && state.reconciliation.ok === false) return true;
    return false;
  }

  function requireTaskRef(value) {
    const ref = core.parseTaskId(String(value || ""));
    if (!ref) throw new Error("Invalid taskId.");
    return ref;
  }

  async function retryReconciliation() {
    const reconciliation = await core.reconcileCurrentWork(taskPort, currentWork);
    state = Object.freeze({...state, reconciliation});
    return reconciliation;
  }

  async function handleMessage(message) {
    await readyPromise;
    const request = message && typeof message === "object" ? message : {};
    const type = String(request.type || "");

    switch (type) {
      case "system.state":
        return {ok: true, state};

      case "system.reconcile": {
        if (state.migration?.ok === false) {
          return {ok: false, reason: "migration-blocked", state};
        }
        const reconciliation = await retryReconciliation();
        return {ok: reconciliation.ok, reconciliation, state};
      }

      case "settings.get":
        return {ok: true, settings: await storage.getSettings()};

      case "settings.save":
        return {
          ok: true,
          settings: await storage.saveSettings(request.patch || {}),
        };

      case "calendars.list":
        return {ok: true, calendars: await taskPort.listCalendars()};

      case "tasks.list":
        return {
          ok: true,
          tasks: await taskPort.listTasks(request.query || {}),
        };

      case "task.page": {
        const ref = requireTaskRef(request.taskId);
        const [task, currentWorkId] = await Promise.all([
          taskPort.getTask(ref),
          currentWork.get(),
        ]);
        return {
          ok: true,
          task,
          model: core.deriveTaskPage({task, currentWorkId}),
          system: state,
        };
      }

      case "task.command": {
        if (blockedForWorkflow()) {
          return {ok: false, reason: "system-blocked", state};
        }

        const ref = requireTaskRef(request.taskId);
        const intent = String(request.intent || "");
        if (
          intent !== "start" &&
          intent !== "stop" &&
          intent !== "complete" &&
          intent !== "cancel"
        ) {
          throw new Error("Unsupported Task command.");
        }

        const result = await workflow[intent](ref);
        if (!result.ok && result.committed) {
          try {
            await retryReconciliation();
          } catch (error) {
            console.error("[CalDAV Assistant] post-command reconciliation failed", error);
          }
        }
        return {ok: result.ok, result, state};
      }

      default:
        return {ok: false, reason: "unsupported-message"};
    }
  }

  browser.runtime.onMessage.addListener(message =>
    handleMessage(message).catch(error => ({
      ok: false,
      reason: "request-failed",
      error: String(error?.message || error),
    }))
  );

  // Explicitly retry initialization after extension lifecycle events. Multiple
  // calls share one promise and do not create a second workflow service.
  function reinitialize() {
    readyPromise = initialize();
    return readyPromise;
  }

  browser.runtime.onInstalled.addListener(() => {
    void reinitialize();
  });
  browser.runtime.onStartup.addListener(() => {
    void reinitialize();
  });
})();
