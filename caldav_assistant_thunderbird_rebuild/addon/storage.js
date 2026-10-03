"use strict";

(() => {
  const SETTINGS_KEY = "caldavAssistant.settings";
  const SETTINGS_MIGRATION_KEY = "caldavAssistant.settingsMigrationV2";
  const CURRENT_WORK_ID_KEY = "caldavAssistant.currentWorkId";

  function asObject(value) {
    return value && typeof value === "object" && !Array.isArray(value)
      ? value
      : {};
  }

  function migrateSettingsObject(value) {
    const source = asObject(value);
    const next = {...source};

    // Work Calendar belonged exclusively to the removed Work-Event framework.
    delete next.workCalendarId;
    next.schemaVersion = 1;

    // Preserve WordPress configuration exactly, including an existing
    // applicationPassword.  It is intentionally never logged or returned in
    // migration summaries.
    if (source.wordpress && typeof source.wordpress === "object") {
      next.wordpress = {...source.wordpress};
    }

    return next;
  }

  function sameJson(a, b) {
    return JSON.stringify(a) === JSON.stringify(b);
  }

  async function ensureSettings() {
    const values = await browser.storage.local.get([
      SETTINGS_KEY,
      SETTINGS_MIGRATION_KEY,
    ]);
    const current = asObject(values[SETTINGS_KEY]);
    const migrated = migrateSettingsObject(current);

    if (!sameJson(current, migrated)) {
      await browser.storage.local.set({[SETTINGS_KEY]: migrated});
      const readBack = await browser.storage.local.get(SETTINGS_KEY);
      if (!sameJson(asObject(readBack[SETTINGS_KEY]), migrated)) {
        throw new Error("Settings migration read-back mismatch.");
      }
    }

    if (values[SETTINGS_MIGRATION_KEY] !== 1) {
      await browser.storage.local.set({[SETTINGS_MIGRATION_KEY]: 1});
    }

    return migrated;
  }

  async function getSettings() {
    return ensureSettings();
  }

  async function saveSettings(patch) {
    const current = await ensureSettings();
    const next = migrateSettingsObject({...current, ...asObject(patch)});
    await browser.storage.local.set({[SETTINGS_KEY]: next});

    const readBack = await browser.storage.local.get(SETTINGS_KEY);
    const stored = asObject(readBack[SETTINGS_KEY]);
    if (!sameJson(stored, next)) {
      throw new Error("Settings write read-back mismatch.");
    }
    return stored;
  }

  async function getCurrentWorkId() {
    const values = await browser.storage.local.get(CURRENT_WORK_ID_KEY);
    const value = values[CURRENT_WORK_ID_KEY];
    return typeof value === "string" && value ? value : null;
  }

  async function setCurrentWorkId(value) {
    if (value === null) {
      await browser.storage.local.remove(CURRENT_WORK_ID_KEY);
      return null;
    }
    if (typeof value !== "string" || !value) {
      throw new Error("currentWorkId must be a non-empty string or null.");
    }

    await browser.storage.local.set({[CURRENT_WORK_ID_KEY]: value});
    const readBack = await getCurrentWorkId();
    if (readBack !== value) {
      throw new Error("currentWorkId write read-back mismatch.");
    }
    return readBack;
  }

  globalThis.RebuildStorage = Object.freeze({
    ensureSettings,
    getSettings,
    saveSettings,
    getCurrentWorkId,
    setCurrentWorkId,
  });
})();
