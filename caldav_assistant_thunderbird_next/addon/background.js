"use strict";

const STARTUP_STATUS_KEY = "caldavAssistant.startupStatus.v2";
const SPACE_NAME = "caldav_assistant";
const TASK_INTENTS = new Set(["start", "stop", "complete", "cancel"]);

let runtimeContext = null;
let startupPromise = null;
let uiPromise = null;

function safeError(error) {
  return String(error?.message || error || "Unknown error");
}

async function saveStartupStatus(value) {
  // Never include settings/config objects here: they may contain credentials.
  await browser.storage.local.set({
    [STARTUP_STATUS_KEY]: {
      timestamp: new Date().toISOString(),
      ...value,
    },
  });
}

async function readStartupStatus() {
  const values = await browser.storage.local.get(STARTUP_STATUS_KEY);
  return values[STARTUP_STATUS_KEY] || null;
}

async function ensureSpace() {
  const url = browser.runtime.getURL("pages/task-picker.html");
  const title =
    browser.i18n.getMessage("extensionName") ||
    "CalDAV Assistant Experimental";
  const existing = await browser.spaces.query({
    name: SPACE_NAME,
    isSelfOwned: true,
  });

  if (existing.length) {
    await browser.spaces.update(existing[0].id, url, {title});
    return existing[0];
  }

  return browser.spaces.create(SPACE_NAME, url, {title});
}

function ensureSpaceOnce() {
  if (!uiPromise) {
    uiPromise = ensureSpace().catch(error => {
      uiPromise = null;
      throw error;
    });
  }
  return uiPromise;
}

async function startup() {
  const Core = globalThis.CalDAVAssistantCore;
  if (!Core) {
    throw new Error("Typed runtime core was not loaded.");
  }

  const storage = new Core.BrowserStorageAdapter(browser.storage.local);
  const tasks = new Core.ThunderbirdTaskRepository(browser.NativeTasks);

  // 1. Settings first. This preserves the old WordPress Application Password
  //    under the same extension ID without ever passing it to diagnostics/UI.
  const settingsMigration = await Core.ensureV2Settings(storage);

  // 2. Convert a pre-clean-room active session before new recovery is allowed
  //    to interpret currentWorkId.
  const activeMigration = await Core.migrateLegacyActiveSession(
    browser.storage.local,
    tasks,
    storage
  );
  if (!activeMigration.ok) {
    runtimeContext = null;
    await saveStartupStatus({
      success: false,
      stage: "legacy-active-session-migration",
      reason: activeMigration.reason,
      settingsMigrated: settingsMigration.migrated,
    });
    return false;
  }

  // 3. Reconcile only from VTODO DESCRIPTION + currentWorkId.
  const recovery = await Core.recoverCurrentWork({
    tasks,
    currentWork: storage,
  });
  if (!recovery.ok) {
    runtimeContext = null;
    await saveStartupStatus({
      success: false,
      stage: "current-work-recovery",
      reason: recovery.message,
      settingsMigrated: settingsMigration.migrated,
      activeSessionMigrated: activeMigration.migrated,
    });
    return false;
  }

  runtimeContext = {
    Core,
    storage,
    tasks,
    taskCommands: new Core.SerialCommandQueue(),
  };

  await saveStartupStatus({
    success: true,
    stage: "ready",
    settingsMigrated: settingsMigration.migrated,
    activeSessionMigrated: activeMigration.migrated,
    recoveryChanged: recovery.changed,
  });
  return true;
}

function startupOnce() {
  if (!startupPromise) {
    startupPromise = startup().catch(async error => {
      runtimeContext = null;
      startupPromise = null;
      try {
        await saveStartupStatus({
          success: false,
          stage: "unexpected",
          reason: safeError(error),
        });
      } catch {
        // A storage failure may reach the console. No settings/secret payload
        // is attached here.
      }
      throw error;
    });
  }
  return startupPromise;
}

async function requireRuntime() {
  await startupOnce();
  return runtimeContext;
}

function messageError(code, message) {
  return {
    ok: false,
    error: {
      code,
      message,
    },
  };
}

function newSessionId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return (
    "session-" +
    Date.now() +
    "-" +
    Math.random().toString(16).slice(2)
  );
}

async function handleMessage(message) {
  if (!message || typeof message !== "object") {
    return messageError("invalid-message", "Invalid request.");
  }

  if (message.type === "startup.status") {
    return {
      ok: true,
      status: await readStartupStatus(),
    };
  }

  const context = await requireRuntime();
  if (!context) {
    const status = await readStartupStatus();
    return messageError(
      "startup-not-ready",
      String(status?.reason || "CalDAV Assistant is not ready.")
    );
  }

  const {Core, storage, tasks} = context;

  if (message.type === "calendars.list") {
    return {
      ok: true,
      calendars: await tasks.listCalendars(),
    };
  }

  if (message.type === "tasks.query") {
    const options = message.options;
    if (!options || typeof options !== "object") {
      return messageError("invalid-query", "Task query options are required.");
    }
    const result = await tasks.query(options);
    return {
      ok: true,
      complete: result.complete,
      failures: result.failures,
      view: Core.deriveTaskPickerView(options, result.items),
    };
  }

  if (message.type === "task.read") {
    const taskId = String(message.taskId || "");
    if (!taskId) {
      return messageError("invalid-task-id", "taskId is required.");
    }
    const task = await tasks.get(taskId);
    if (!task) {
      return messageError("task-not-found", "Task not found.");
    }
    const currentWorkId = await storage.get();
    return {
      ok: true,
      view: Core.deriveTaskPageView(
        task,
        currentWorkId,
        new Date().toISOString()
      ),
    };
  }

  if (message.type === "task.command") {
    const taskId = String(message.taskId || "");
    const intent = String(message.intent || "");
    if (!taskId) {
      return messageError("invalid-task-id", "taskId is required.");
    }
    if (!TASK_INTENTS.has(intent)) {
      return messageError("invalid-intent", "Unsupported Task action.");
    }

    return context.taskCommands.run(async () => {
      const result = await Core.runTaskCommand(
        {
          tasks,
          currentWork: storage,
        },
        intent,
        taskId,
        new Date().toISOString(),
        newSessionId()
      );
      return {ok: true, result};
    });
  }

  if (message.type === "today.read") {
    const date = String(message.date || "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      return messageError("invalid-date", "Expected YYYY-MM-DD.");
    }
    const scan = await tasks.scanStored();
    return {
      ok: true,
      complete: scan.complete,
      failures: scan.failures,
      view: Core.deriveTodayView(scan.tasks, date),
    };
  }

  return messageError("unknown-message", "Unsupported request.");
}

browser.runtime.onMessage.addListener(message =>
  handleMessage(message).catch(error =>
    messageError("internal-error", safeError(error))
  )
);

browser.runtime.onInstalled.addListener(() => {
  void ensureSpaceOnce().catch(error =>
    console.error("[CalDAV Assistant] Space setup failed", safeError(error))
  );
  void startupOnce().catch(error =>
    console.error("[CalDAV Assistant] startup failed", safeError(error))
  );
});

browser.runtime.onStartup.addListener(() => {
  void ensureSpaceOnce().catch(error =>
    console.error("[CalDAV Assistant] Space setup failed", safeError(error))
  );
  void startupOnce().catch(error =>
    console.error("[CalDAV Assistant] startup failed", safeError(error))
  );
});

void ensureSpaceOnce().catch(error =>
  console.error("[CalDAV Assistant] Space setup failed", safeError(error))
);

void startupOnce().catch(error =>
  console.error("[CalDAV Assistant] startup failed", safeError(error))
);
