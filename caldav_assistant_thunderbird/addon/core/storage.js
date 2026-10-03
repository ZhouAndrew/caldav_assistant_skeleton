"use strict";

(() => {
  const KEY_SETTINGS = "caldavAssistant.settings";
  const KEY_SETTINGS_UNDO = "caldavAssistant.settingsUndo";
  const KEY_RUNTIME = "caldavAssistant.runtime";
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
    return value;
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

  function makeWorkTaskId(ref) {
    if (!ref?.calendarId || !ref?.id) return null;
    return [
      encodeURIComponent(String(ref.calendarId)),
      encodeURIComponent(String(ref.id)),
      encodeURIComponent(String(ref.recurrenceId || "")),
    ].join("|");
  }

  function parseWorkTaskId(value) {
    if (typeof value !== "string") return null;
    const parts = value.split("|");
    if (parts.length !== 3) return null;
    try {
      return {
        calendarId: decodeURIComponent(parts[0]),
        id: decodeURIComponent(parts[1]),
        recurrenceId: decodeURIComponent(parts[2]),
      };
    } catch (_error) {
      return null;
    }
  }

  async function getLegacyRuntime() {
    return getValue(KEY_RUNTIME, {
      state: "idle",
      currentTask: null,
      currentWorkEvent: null,
      segmentStartedAtMs: null,
      accumulatedMs: 0,
    });
  }

  async function getCurrentWorkId() {
    const values = await browser.storage.local.get([
      KEY_CURRENT_WORK_ID,
      KEY_RUNTIME,
    ]);

    if (values[KEY_CURRENT_WORK_ID] !== undefined) {
      const stored = values[KEY_CURRENT_WORK_ID];
      if (stored === null || parseWorkTaskId(stored)) return stored;
    }

    const legacyRuntime = values[KEY_RUNTIME] || null;
    const migrated = makeWorkTaskId(legacyRuntime?.currentTask);
    await setValue(KEY_CURRENT_WORK_ID, migrated);

    if (migrated) {
      try {
        await appendAudit({
          scope: "migration",
          action: "legacy-runtime-baseline",
          success: true,
          summary: "Migrated active 0.3.15 work state into immutable history.",
          details: {
            task: {
              id: legacyRuntime.currentTask.id,
              calendarId: legacyRuntime.currentTask.calendarId,
              recurrenceId: String(legacyRuntime.currentTask.recurrenceId || ""),
              title: String(legacyRuntime.currentTask.title || ""),
            },
            state: String(legacyRuntime.state || ""),
            accumulatedMs: Math.max(0, Number(legacyRuntime.accumulatedMs || 0)),
            segmentStartedAtMs: legacyRuntime.segmentStartedAtMs
              ? Number(legacyRuntime.segmentStartedAtMs)
              : null,
            currentWorkEvent: legacyRuntime.currentWorkEvent || null,
            taskBeforeStart: legacyRuntime.taskBeforeStart || null,
          },
        });
      } catch (_error) {
        // CalDAV/currentWorkId migration must not depend on auxiliary audit I/O.
      }
    }
    return migrated;
  }

  async function setCurrentWorkId(value) {
    if (value !== null && !parseWorkTaskId(value)) {
      throw new Error("Invalid currentWorkId.");
    }
    await setValue(KEY_CURRENT_WORK_ID, value);
    if (value === null) {
      try {
        await browser.storage.local.remove(KEY_RUNTIME);
      } catch (_error) {
        // Stale legacy data is harmless once an explicit null pointer exists.
      }
    }
    return value;
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

  async function findLatestStartSnapshot(task) {
    const targetWorkId = makeWorkTaskId(task);
    if (!targetWorkId) return null;

    const records = await listAudit();
    for (let index = records.length - 1; index >= 0; index--) {
      const record = records[index];
      if (record?.scope !== "workflow" || record?.action !== "start") continue;
      if (record?.success === false || record?.details?.success === false) continue;

      const receiptTask = record?.details?.task;
      if (makeWorkTaskId(receiptTask) !== targetWorkId) continue;

      const status = String(receiptTask?.beforeStatus || "NEEDS-ACTION");
      if (status === "COMPLETED" || status === "CANCELLED") continue;

      return Object.freeze({
        status,
        paused: Boolean(receiptTask?.beforePaused),
        percentComplete: Math.min(
          99,
          Math.max(0, Number(receiptTask?.beforePercentComplete || 0))
        ),
      });
    }
    return null;
  }

  function auditTimestampMs(record) {
    const value =
      record?.details?.completedAt ||
      record?.timestamp ||
      record?.details?.startedAt ||
      "";
    const parsed = Date.parse(String(value));
    return Number.isFinite(parsed) ? parsed : null;
  }

  async function findOpenWorkSessionRef(task) {
    const targetWorkId = makeWorkTaskId(task);
    if (!targetWorkId) return null;

    const records = await listAudit();
    for (let index = records.length - 1; index >= 0; index--) {
      const record = records[index];
      if (record?.scope !== "workflow") continue;
      if (record?.success === false || record?.details?.success === false) continue;
      if (makeWorkTaskId(record?.details?.task) !== targetWorkId) continue;

      if (
        record.action === "pause" ||
        record.action === "complete" ||
        record.action === "cancel" ||
        record.action === "switch-away"
      ) {
        return null;
      }

      if (record.action !== "start" && record.action !== "resume") continue;

      const steps = Array.isArray(record?.details?.steps)
        ? record.details.steps
        : [];
      const created = steps.find(step =>
        step?.component === "Work Session" &&
        step?.operation === "create VEVENT" &&
        step?.success !== false &&
        step?.details?.uid &&
        step?.details?.calendarId
      );
      if (created) {
        return Object.freeze({
          id: String(created.details.uid),
          calendarId: String(created.details.calendarId),
          source: "audit",
        });
      }
      break;
    }

    // Migration fallback for an active 0.3.15 session whose Start/Resume audit
    // predates the structured Work-session receipt.
    const runtime = await getLegacyRuntime();
    if (
      makeWorkTaskId(runtime?.currentTask) === targetWorkId &&
      runtime?.currentWorkEvent?.id &&
      runtime?.currentWorkEvent?.calendarId
    ) {
      return Object.freeze({
        id: String(runtime.currentWorkEvent.id),
        calendarId: String(runtime.currentWorkEvent.calendarId),
        source: "legacy-runtime",
      });
    }

    return null;
  }

  async function deriveWorkTiming(task) {
    const targetWorkId = makeWorkTaskId(task);
    if (!targetWorkId) {
      return Object.freeze({
        accumulatedMs: 0,
        segmentStartedAtMs: null,
        source: "none",
      });
    }

    const records = await listAudit();
    let accumulatedMs = 0;
    let segmentStartedAtMs = null;
    let sessionSeen = false;
    let historySeen = false;

    for (const record of records) {
      if (record?.success === false || record?.details?.success === false) continue;
      if (makeWorkTaskId(record?.details?.task) !== targetWorkId) continue;

      if (record.action === "legacy-runtime-baseline") {
        accumulatedMs = Math.max(0, Number(record?.details?.accumulatedMs || 0));
        segmentStartedAtMs =
          String(record?.details?.state || "") === "working" &&
          Number(record?.details?.segmentStartedAtMs) > 0
            ? Number(record.details.segmentStartedAtMs)
            : null;
        sessionSeen = true;
        historySeen = true;
        continue;
      }

      if (record?.scope !== "workflow") continue;
      const atMs = auditTimestampMs(record);
      if (atMs === null) continue;

      switch (record.action) {
        case "start":
          accumulatedMs = 0;
          segmentStartedAtMs = atMs;
          sessionSeen = true;
          historySeen = true;
          break;

        case "pause":
          if (sessionSeen && segmentStartedAtMs !== null) {
            accumulatedMs += Math.max(0, atMs - segmentStartedAtMs);
            segmentStartedAtMs = null;
          }
          historySeen = true;
          break;

        case "resume":
          if (sessionSeen && segmentStartedAtMs === null) {
            segmentStartedAtMs = atMs;
          }
          historySeen = true;
          break;

        case "complete":
        case "cancel":
        case "switch-away":
          if (sessionSeen && segmentStartedAtMs !== null) {
            accumulatedMs += Math.max(0, atMs - segmentStartedAtMs);
          }
          segmentStartedAtMs = null;
          sessionSeen = false;
          historySeen = true;
          break;
      }
    }

    if (historySeen && sessionSeen) {
      return Object.freeze({
        accumulatedMs,
        segmentStartedAtMs,
        source: "audit",
      });
    }

    // Compatibility for a profile whose currentWorkId was migrated by an
    // earlier transitional build before immutable baseline records existed.
    // predates the new deterministic timing derivation.
    const runtime = await getLegacyRuntime();
    if (makeWorkTaskId(runtime?.currentTask) === targetWorkId) {
      return Object.freeze({
        accumulatedMs: Math.max(0, Number(runtime?.accumulatedMs || 0)),
        segmentStartedAtMs: runtime?.segmentStartedAtMs
          ? Number(runtime.segmentStartedAtMs)
          : null,
        source: "legacy-runtime",
      });
    }

    return Object.freeze({
      accumulatedMs: 0,
      segmentStartedAtMs: null,
      source: historySeen ? "audit-closed" : "none",
    });
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
    makeWorkTaskId,
    parseWorkTaskId,
    getCurrentWorkId,
    setCurrentWorkId,
    getLegacyRuntime,
    appendAudit,
    listAudit,
    findLatestStartSnapshot,
    findOpenWorkSessionRef,
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
