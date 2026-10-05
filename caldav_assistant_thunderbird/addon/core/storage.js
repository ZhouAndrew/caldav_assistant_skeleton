"use strict";

(() => {
  const KEY_SETTINGS = "caldavAssistant.settings";
  const KEY_SETTINGS_UNDO = "caldavAssistant.settingsUndo";
  const KEY_CURRENT_WORK_ID = "caldavAssistant.currentWorkId";
  const KEY_AUDIT_LEGACY = "caldavAssistant.audit";
  const KEY_AUDIT_DATES = "caldavAssistant.auditDates";
  const KEY_AUDIT_PREFIX = "caldavAssistant.audit.";
  const KEY_RECEIPT = "caldavAssistant.lastReceipt";
  const KEY_WP_OUTBOX = "caldavAssistant.wordpressOutbox";
  const MAX_AUDIT_RECORDS_PER_DAY = 1000;
  const MAX_OUTBOX_RECORDS = 500;
  let auditMigrationDone = false;

  function nowIso() {
    return new Date().toISOString();
  }

  function localDateKey(value = new Date()) {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return (
      String(date.getFullYear()).padStart(4, "0") + "-" +
      String(date.getMonth() + 1).padStart(2, "0") + "-" +
      String(date.getDate()).padStart(2, "0")
    );
  }

  function auditKey(dateKey) {
    return KEY_AUDIT_PREFIX + dateKey;
  }

  function makeId(prefix = "audit") {
    if (globalThis.crypto?.randomUUID) {
      return `${prefix}-${crypto.randomUUID()}`;
    }
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  async function getValue(key, fallback) {
    const values = await browser.storage.local.get(key);
    return values[key] === undefined ? fallback : values[key];
  }

  async function setValue(key, value) {
    await browser.storage.local.set({[key]: value});
    const actual = await getValue(key, null);
    if (JSON.stringify(actual) !== JSON.stringify(value)) throw new Error("Storage read-back mismatch: " + key);
    return actual;
  }

  async function getSettings() {
    return getValue(KEY_SETTINGS, {});
  }

  async function saveSettings(patch) {
    const current = await getSettings();
    const next = {...current, ...(patch || {})};
    return setValue(KEY_SETTINGS, next);
  }

  async function saveSettingsWithUndo(patch) {
    const current = await getSettings();
    const changes = patch || {};
    const keys = Object.keys(changes);
    const previous = {};
    const existed = {};

    for (const key of keys) {
      existed[key] = Object.prototype.hasOwnProperty.call(current, key);
      if (existed[key]) previous[key] = current[key];
    }

    const next = {...current, ...changes};
    await setValue(KEY_SETTINGS_UNDO, {
      keys,
      previous,
      existed,
      timestamp: nowIso(),
    });
    await setValue(KEY_SETTINGS, next);
    return {keys, next};
  }

  async function getSettingsUndo() {
    return getValue(KEY_SETTINGS_UNDO, null);
  }

  async function undoSettings() {
    const snapshot = await getSettingsUndo();
    if (!snapshot) return null;

    if (!Array.isArray(snapshot.keys) && snapshot.previous) {
      await setValue(KEY_SETTINGS, snapshot.previous);
      await setValue(KEY_SETTINGS_UNDO, null);
      return snapshot.previous;
    }

    const current = await getSettings();
    const restored = {...current};
    for (const key of snapshot.keys || []) {
      if (snapshot.existed?.[key]) {
        restored[key] = snapshot.previous?.[key];
      } else {
        delete restored[key];
      }
    }
    await setValue(KEY_SETTINGS, restored);
    await setValue(KEY_SETTINGS_UNDO, null);
    return restored;
  }

  async function getCurrentWorkId() {
    const stored = await getValue(KEY_CURRENT_WORK_ID, null);
    AssistantActionPlan.parseIdentity(stored);
    return stored;
  }

  async function setCurrentWorkId(value) {
    AssistantActionPlan.parseIdentity(value);
    await setValue(KEY_CURRENT_WORK_ID, value);
    const actual = await getCurrentWorkId();
    if (actual !== value) throw new Error("CurrentWorkId read-back mismatch");
    return actual;
  }

  async function getAuditDatesRaw() {
    const dates = await getValue(KEY_AUDIT_DATES, []);
    return Array.isArray(dates)
      ? dates.filter(value => /^\d{4}-\d{2}-\d{2}$/.test(value))
      : [];
  }

  async function saveAuditDates(dates) {
    const normalized = [...new Set(dates)].sort().reverse();
    await setValue(KEY_AUDIT_DATES, normalized);
    return normalized;
  }

  async function migrateLegacyAudit() {
    if (auditMigrationDone) return;
    auditMigrationDone = true;
    const legacy = await getValue(KEY_AUDIT_LEGACY, null);
    if (!Array.isArray(legacy) || !legacy.length) {
      if (legacy !== null) await browser.storage.local.remove(KEY_AUDIT_LEGACY);
      return;
    }

    const grouped = new Map();
    for (const item of legacy) {
      const dateKey = localDateKey(item?.timestamp || nowIso()) || localDateKey();
      if (!grouped.has(dateKey)) grouped.set(dateKey, []);
      grouped.get(dateKey).push({...item, localDate: dateKey});
    }

    const dates = await getAuditDatesRaw();
    for (const [dateKey, items] of grouped.entries()) {
      const existing = await getValue(auditKey(dateKey), []);
      const merged = Array.isArray(existing) ? [...existing] : [];
      const ids = new Set(merged.map(item => item?.id).filter(Boolean));
      for (const item of items) {
        if (!item.id || !ids.has(item.id)) {
          merged.push(item);
          if (item.id) ids.add(item.id);
        }
      }
      merged.sort((a, b) =>
        String(a.timestamp || "").localeCompare(String(b.timestamp || ""))
      );
      if (merged.length > MAX_AUDIT_RECORDS_PER_DAY) {
        merged.splice(0, merged.length - MAX_AUDIT_RECORDS_PER_DAY);
      }
      await setValue(auditKey(dateKey), merged);
      dates.push(dateKey);
    }
    await saveAuditDates(dates);
    await browser.storage.local.remove(KEY_AUDIT_LEGACY);
  }

  async function appendAudit(entry) {
    await migrateLegacyAudit();
    const timestamp = entry?.timestamp || nowIso();
    const dateKey = localDateKey(timestamp) || localDateKey();
    const record = {
      id: entry?.id || makeId(),
      timestamp,
      localDate: dateKey,
      scope: String(entry?.scope || "system"),
      action: String(entry?.action || "unknown"),
      success: entry?.success !== false,
      summary: String(entry?.summary || ""),
      details: entry?.details ?? null,
    };

    const key = auditKey(dateKey);
    const records = await getValue(key, []);
    const next = Array.isArray(records) ? [...records, record] : [record];
    if (next.length > MAX_AUDIT_RECORDS_PER_DAY) {
      next.splice(0, next.length - MAX_AUDIT_RECORDS_PER_DAY);
    }
    await setValue(key, next);

    const dates = await getAuditDatesRaw();
    if (!dates.includes(dateKey)) await saveAuditDates([...dates, dateKey]);
    return record;
  }

  async function listAuditDates() {
    await migrateLegacyAudit();
    return getAuditDatesRaw();
  }

  async function listAudit(dateKey = "") {
    await migrateLegacyAudit();
    if (dateKey) {
      const records = await getValue(auditKey(dateKey), []);
      return Array.isArray(records) ? records : [];
    }

    const output = [];
    for (const date of (await getAuditDatesRaw()).slice().reverse()) {
      const records = await getValue(auditKey(date), []);
      if (Array.isArray(records)) output.push(...records);
    }
    return output.sort((a, b) =>
      String(a.timestamp || "").localeCompare(String(b.timestamp || ""))
    );
  }

  async function deriveWorkTiming(task) {
    const session = AssistantActionPlan.sessions(task.description || "").find(item => item.end === null);
    return Object.freeze({accumulatedMs:0, segmentStartedAtMs:session ? Date.parse(session.start) : null, source:"VTODO"});
  }

  async function clearAudit(dateKey = "") {
    await migrateLegacyAudit();
    if (dateKey) {
      await browser.storage.local.remove(auditKey(dateKey));
      await saveAuditDates(
        (await getAuditDatesRaw()).filter(value => value !== dateKey)
      );
      return;
    }

    const dates = await getAuditDatesRaw();
    await browser.storage.local.remove([
      ...dates.map(auditKey),
      KEY_AUDIT_DATES,
      KEY_AUDIT_LEGACY,
    ]);
  }

  async function enqueueWordPressOutbox(entry) {
    const records = await getValue(KEY_WP_OUTBOX, []);
    const item = {
      id: entry?.id || makeId("wp-outbox"),
      createdAt: entry?.createdAt || nowIso(),
      updatedAt: nowIso(),
      attempts: Number(entry?.attempts || 0),
      lastError: String(entry?.lastError || ""),
      payload: entry?.payload ?? entry,
    };
    const next = Array.isArray(records) ? [...records, item] : [item];
    if (next.length > MAX_OUTBOX_RECORDS) {
      next.splice(0, next.length - MAX_OUTBOX_RECORDS);
    }
    await setValue(KEY_WP_OUTBOX, next);
    return item;
  }

  async function listWordPressOutbox() {
    const records = await getValue(KEY_WP_OUTBOX, []);
    return Array.isArray(records) ? records : [];
  }

  async function updateWordPressOutbox(id, patch) {
    const records = await listWordPressOutbox();
    const index = records.findIndex(item => item.id === id);
    if (index < 0) return null;
    records[index] = {...records[index], ...(patch || {}), updatedAt: nowIso()};
    await setValue(KEY_WP_OUTBOX, records);
    return records[index];
  }

  async function removeWordPressOutbox(id) {
    const records = await listWordPressOutbox();
    const next = records.filter(item => item.id !== id);
    await setValue(KEY_WP_OUTBOX, next);
    return next.length !== records.length;
  }

  async function saveLastReceipt(receipt) {
    await setValue(KEY_RECEIPT, receipt);
    return receipt;
  }

  async function getLastReceipt() {
    return getValue(KEY_RECEIPT, null);
  }

  async function persistResult(result, scope = "system") {
    const value = result || {};
    value.logSaved = true;
    value.logError = null;

    try {
      await appendAudit({
        scope,
        action: value.action || "unknown",
        success: value.success !== false,
        summary: value.summary || "",
        details: value,
      });
    } catch (error) {
      value.logSaved = false;
      value.logError = String(error?.message || error || "Unknown log error");
    }

    try {
      await saveLastReceipt(value);
    } catch (error) {
      value.cacheSaved = false;
      value.cacheError = String(error?.message || error || "Unknown receipt cache error");
    }
    return value;
  }

  globalThis.AssistantStorage = Object.freeze({
    getSettings,
    saveSettings,
    saveSettingsWithUndo,
    getSettingsUndo,
    undoSettings,
    getCurrentWorkId,
    setCurrentWorkId,
    appendAudit,
    listAudit,
    deriveWorkTiming,
    listAuditDates,
    clearAudit,
    localDateKey,
    enqueueWordPressOutbox,
    listWordPressOutbox,
    updateWordPressOutbox,
    removeWordPressOutbox,
    saveLastReceipt,
    getLastReceipt,
    persistResult,
  });
})();
