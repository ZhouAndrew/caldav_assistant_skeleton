"use strict";

(() => {
  const KEY_MIGRATION = "caldavAssistant.cleanroomMigrationV1";
  const KEY_CURRENT = "caldavAssistant.currentWorkId";
  const KEY_RUNTIME = "caldavAssistant.runtime";
  const KEY_RECEIPT = "caldavAssistant.lastReceipt";
  const KEY_AUDIT_LEGACY = "caldavAssistant.audit";
  const KEY_AUDIT_DATES = "caldavAssistant.auditDates";
  const KEY_AUDIT_PREFIX = "caldavAssistant.audit.";

  async function getOne(key) {
    const values = await browser.storage.local.get(key);
    return values[key];
  }

  async function isComplete() {
    return (await getOne(KEY_MIGRATION)) === 1;
  }

  async function getRawCurrentWorkId() {
    return getOne(KEY_CURRENT);
  }

  async function getLegacyRuntime() {
    return getOne(KEY_RUNTIME);
  }

  async function getLastReceipt() {
    return getOne(KEY_RECEIPT);
  }

  async function listAuditRecords() {
    const values = await browser.storage.local.get([
      KEY_AUDIT_DATES,
      KEY_AUDIT_LEGACY,
    ]);
    const output = [];

    if (Array.isArray(values[KEY_AUDIT_LEGACY])) {
      output.push(...values[KEY_AUDIT_LEGACY]);
    }

    const dates = Array.isArray(values[KEY_AUDIT_DATES])
      ? values[KEY_AUDIT_DATES].filter(value =>
          /^\d{4}-\d{2}-\d{2}$/.test(String(value))
        )
      : [];

    for (const date of dates) {
      const key = KEY_AUDIT_PREFIX + date;
      const records = await getOne(key);
      if (Array.isArray(records)) output.push(...records);
    }

    return output.sort((a, b) =>
      String(a?.timestamp || "").localeCompare(String(b?.timestamp || ""))
    );
  }

  async function setCurrentWorkId(value) {
    await globalThis.RebuildStorage.setCurrentWorkId(value);
  }

  async function removeLegacyRuntime() {
    await browser.storage.local.remove(KEY_RUNTIME);
  }

  async function markComplete() {
    await browser.storage.local.set({[KEY_MIGRATION]: 1});
    if ((await getOne(KEY_MIGRATION)) !== 1) {
      throw new Error("Legacy migration marker read-back mismatch.");
    }
  }

  globalThis.RebuildLegacyStore = Object.freeze({
    isComplete,
    getRawCurrentWorkId,
    getLegacyRuntime,
    getLastReceipt,
    listAuditRecords,
    setCurrentWorkId,
    removeLegacyRuntime,
    markComplete,
  });
})();
