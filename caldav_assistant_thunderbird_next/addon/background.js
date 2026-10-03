"use strict";

const STARTUP_STATUS_KEY = "caldavAssistant.startupStatus.v2";

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

async function startup() {
  const Core = globalThis.CalDAVAssistantCore;
  if (!Core) {
    throw new Error("Typed runtime core was not loaded.");
  }

  const storage = new Core.BrowserStorageAdapter(browser.storage.local);
  const tasks = new Core.ThunderbirdTaskRepository(browser.NativeTasks);

  // 1. Settings first. This preserves the old WordPress Application Password
  //    under the same extension ID without ever passing it to diagnostics.
  const settingsMigration = await Core.ensureV2Settings(storage);

  // 2. Convert a pre-clean-room active session before new recovery is allowed
  //    to interpret currentWorkId.
  const activeMigration = await Core.migrateLegacyActiveSession(
    browser.storage.local,
    tasks,
    storage
  );
  if (!activeMigration.ok) {
    await saveStartupStatus({
      success: false,
      stage: "legacy-active-session-migration",
      reason: activeMigration.reason,
      settingsMigrated: settingsMigration.migrated,
    });
    return;
  }

  // 3. Reconcile only from VTODO DESCRIPTION + currentWorkId.
  const recovery = await Core.recoverCurrentWork({
    tasks,
    currentWork: storage,
  });
  if (!recovery.ok) {
    await saveStartupStatus({
      success: false,
      stage: "current-work-recovery",
      reason: recovery.message,
      settingsMigrated: settingsMigration.migrated,
      activeSessionMigrated: activeMigration.migrated,
    });
    return;
  }

  await saveStartupStatus({
    success: true,
    stage: "ready",
    settingsMigrated: settingsMigration.migrated,
    activeSessionMigrated: activeMigration.migrated,
    recoveryChanged: recovery.changed,
  });
}

let startupPromise = null;

function startupOnce() {
  if (!startupPromise) {
    startupPromise = startup().catch(async error => {
      startupPromise = null;
      try {
        await saveStartupStatus({
          success: false,
          stage: "unexpected",
          reason: safeError(error),
        });
      } catch {
        // A storage failure is allowed to reach the console, but no secret
        // payload is ever attached to it.
      }
      throw error;
    });
  }
  return startupPromise;
}

browser.runtime.onInstalled.addListener(() => {
  void startupOnce().catch(error =>
    console.error("[CalDAV Assistant] startup failed", safeError(error))
  );
});

browser.runtime.onStartup.addListener(() => {
  void startupOnce().catch(error =>
    console.error("[CalDAV Assistant] startup failed", safeError(error))
  );
});

void startupOnce().catch(error =>
  console.error("[CalDAV Assistant] startup failed", safeError(error))
);
