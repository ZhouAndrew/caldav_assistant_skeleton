import {TaskRepository} from "../ports";
import {CurrentWorkStore} from "../ports";
import {StorageArea} from "../adapters/browser-storage";
import {TaskStatus, WorkSession} from "../domain";
import {
  openSession,
  openWorkSession,
  parseWorkDescription,
  serializeWorkDescription,
} from "../work-description";
import {encodeTaskId} from "../task-id";

const KEY_RUNTIME = "caldavAssistant.runtime";
const KEY_AUDIT_LEGACY = "caldavAssistant.audit";
const KEY_AUDIT_DATES = "caldavAssistant.auditDates";
const KEY_LAST_RECEIPT = "caldavAssistant.lastReceipt";
const KEY_MIGRATED = "caldavAssistant.migration.activeSession.v1";

type RecordLike = Record<string, unknown>;

export interface LegacyActiveMigrationResult {
  readonly ok: boolean;
  readonly migrated: boolean;
  readonly reason: string;
}

function object(value: unknown): RecordLike | null {
  return value && typeof value === "object"
    ? value as RecordLike
    : null;
}

function validStatus(value: unknown): TaskStatus | null {
  return value === "NEEDS-ACTION" || value === "IN-PROCESS"
    ? value
    : null;
}

function percent(value: unknown): number | null {
  const n = Number(value);
  return Number.isInteger(n) && n >= 0 && n < 100 ? n : null;
}

function iso(value: unknown): string | null {
  const text = typeof value === "string" ? value : "";
  return text && Number.isFinite(Date.parse(text)) ? text : null;
}

function workIdFromLegacyTask(value: unknown): string | null {
  const task = object(value);
  if (!task) return null;
  const calendarId = typeof task.calendarId === "string" ? task.calendarId : "";
  const uid =
    typeof task.id === "string"
      ? task.id
      : typeof task.uid === "string"
        ? task.uid
        : "";
  const recurrenceId =
    typeof task.recurrenceId === "string" ? task.recurrenceId : "";
  if (!calendarId || !uid) return null;
  return encodeTaskId({calendarId, uid, recurrenceId});
}

function auditTime(record: RecordLike): number {
  const details = object(record.details);
  for (const candidate of [
    details?.completedAt,
    record.timestamp,
    details?.startedAt,
  ]) {
    const parsed = Date.parse(String(candidate || ""));
    if (Number.isFinite(parsed)) return parsed;
  }
  return -1;
}

function successfulWorkflowFor(
  records: readonly unknown[],
  currentWorkId: string
): RecordLike[] {
  return records
    .map(object)
    .filter((record): record is RecordLike => Boolean(record))
    .filter(record => {
      if (record.scope !== "workflow") return false;
      if (record.success === false) return false;
      const details = object(record.details);
      if (!details || details.success === false) return false;
      return workIdFromLegacyTask(details.task) === currentWorkId;
    })
    .sort((a, b) => auditTime(a) - auditTime(b));
}

function recoverFromAudit(
  records: readonly unknown[],
  currentWorkId: string
): WorkSession | "closed" | null {
  const relevant = successfulWorkflowFor(records, currentWorkId);
  if (!relevant.length) return null;

  const lifecycle = relevant.filter(record =>
    ["start", "stop", "complete", "cancel", "pause", "resume", "switch-away"]
      .includes(String(record.action || ""))
  );
  if (!lifecycle.length) return null;

  const latest = lifecycle[lifecycle.length - 1]!;
  const latestAction = String(latest.action || "");
  if (["stop", "complete", "cancel", "switch-away"].includes(latestAction)) {
    return "closed";
  }
  if (latestAction === "pause") return null;

  let start: RecordLike | null = null;
  for (let i = lifecycle.length - 1; i >= 0; i--) {
    const record = lifecycle[i]!;
    const action = String(record.action || "");
    if (action === "start") {
      start = record;
      break;
    }
    if (["stop", "complete", "cancel", "switch-away"].includes(action)) {
      break;
    }
  }
  if (!start) return null;

  const details = object(start.details);
  const task = object(details?.task);
  const startedAt = iso(details?.startedAt) ??
    iso(start.timestamp);
  const beforeStatus = validStatus(task?.beforeStatus);
  const beforePercent = percent(task?.beforePercentComplete);
  if (!startedAt || !beforeStatus || beforePercent === null) return null;

  return Object.freeze({
    id: "legacy-" + String(start.id || startedAt),
    start: startedAt,
    end: null,
    result: null,
    before: Object.freeze({
      status: beforeStatus,
      percentComplete: beforePercent,
    }),
  });
}

function recoverFromRuntime(
  runtimeValue: unknown,
  currentWorkId: string
): WorkSession | null {
  const runtime = object(runtimeValue);
  if (!runtime) return null;
  if (workIdFromLegacyTask(runtime.currentTask) !== currentWorkId) return null;
  if (String(runtime.state || "") !== "working") return null;

  const before = object(runtime.taskBeforeStart);
  const beforeStatus = validStatus(before?.status);
  const beforePercent = percent(before?.percentComplete);
  const startedMs = Number(runtime.segmentStartedAtMs);
  if (
    !beforeStatus ||
    beforePercent === null ||
    !Number.isFinite(startedMs) ||
    startedMs <= 0
  ) {
    return null;
  }

  return Object.freeze({
    id: "legacy-runtime-" + String(Math.trunc(startedMs)),
    start: new Date(startedMs).toISOString(),
    end: null,
    result: null,
    before: Object.freeze({
      status: beforeStatus,
      percentComplete: beforePercent,
    }),
  });
}

async function readLegacyRecords(storage: StorageArea): Promise<unknown[]> {
  const head = await storage.get([
    KEY_AUDIT_DATES,
    KEY_AUDIT_LEGACY,
    KEY_LAST_RECEIPT,
  ]);
  const records: unknown[] = [];

  const legacy = head[KEY_AUDIT_LEGACY];
  if (Array.isArray(legacy)) records.push(...legacy);

  const dates = head[KEY_AUDIT_DATES];
  if (Array.isArray(dates)) {
    const keys = dates
      .filter((value): value is string => typeof value === "string" && Boolean(value))
      .map(value => "caldavAssistant.audit." + value);
    if (keys.length) {
      const values = await storage.get(keys);
      for (const key of keys) {
        const daily = values[key];
        if (Array.isArray(daily)) records.push(...daily);
      }
    }
  }

  const receipt = object(head[KEY_LAST_RECEIPT]);
  if (receipt) {
    records.push({
      id: receipt.id,
      timestamp: receipt.completedAt ?? receipt.startedAt,
      scope: "workflow",
      action: receipt.action,
      success: receipt.success,
      details: receipt,
    });
  }

  return records;
}

/**
 * Migrate one active pre-clean-room session into the Task's own DESCRIPTION.
 *
 * Legacy data is migration input only. After this function succeeds, normal
 * runtime code never reads it.
 */
export async function migrateLegacyActiveSession(
  storage: StorageArea,
  tasks: TaskRepository,
  currentWork: CurrentWorkStore
): Promise<LegacyActiveMigrationResult> {
  const marker = await storage.get(KEY_MIGRATED);
  if (marker[KEY_MIGRATED] === true) {
    return {ok: true, migrated: false, reason: "already-migrated"};
  }

  const currentWorkId = await currentWork.get();
  if (currentWorkId === null) {
    await storage.set({[KEY_MIGRATED]: true});
    await storage.remove(KEY_RUNTIME);
    return {ok: true, migrated: false, reason: "no-active-task"};
  }

  const task = await tasks.get(currentWorkId);
  if (!task) {
    return {ok: false, migrated: false, reason: "current-task-not-readable"};
  }

  const parsed = parseWorkDescription(task.description);
  if (!parsed.ok) {
    return {ok: false, migrated: false, reason: "description-invalid"};
  }
  if (openWorkSession(parsed.value)) {
    await storage.set({[KEY_MIGRATED]: true});
    await storage.remove(KEY_RUNTIME);
    return {ok: true, migrated: false, reason: "already-new-format"};
  }

  const records = await readLegacyRecords(storage);
  const auditRecovered = recoverFromAudit(records, currentWorkId);
  if (auditRecovered === "closed") {
    // The pointer is stale. Do not invent a session; allow new recovery to clear it.
    await storage.set({[KEY_MIGRATED]: true});
    await storage.remove(KEY_RUNTIME);
    return {ok: true, migrated: false, reason: "legacy-session-already-closed"};
  }

  const runtimeValues = await storage.get(KEY_RUNTIME);
  const recovered =
    auditRecovered ??
    recoverFromRuntime(runtimeValues[KEY_RUNTIME], currentWorkId);
  if (!recovered) {
    return {
      ok: false,
      migrated: false,
      reason: "legacy-active-session-unrecoverable",
    };
  }

  const opened = openSession(parsed.value, recovered);
  if (!opened) {
    return {ok: false, migrated: false, reason: "cannot-open-migrated-session"};
  }

  await tasks.update(
    currentWorkId,
    {
      description: serializeWorkDescription(opened),
      status: task.status,
      percentComplete: task.percentComplete,
    },
    {
      description: task.description,
      status: task.status,
      percentComplete: task.percentComplete,
    }
  );

  const verified = await tasks.get(currentWorkId);
  if (
    !verified ||
    verified.description !== serializeWorkDescription(opened) ||
    verified.status !== task.status ||
    verified.percentComplete !== task.percentComplete
  ) {
    return {ok: false, migrated: false, reason: "migration-readback-failed"};
  }

  await storage.set({[KEY_MIGRATED]: true});
  await storage.remove(KEY_RUNTIME);
  return {ok: true, migrated: true, reason: "migrated"};
}
