import {
  TaskRef,
  TaskSnapshot,
  TaskStatus,
  WorkSession,
} from "./domain.js";
import {makeTaskId, parseTaskId} from "./task-id.js";
import {
  getOpenSession,
  openWorkSession,
  parseWorkDescription,
  serializeWorkDescription,
} from "./work-description.js";
import {
  CurrentWorkPort,
  ThunderbirdTaskPort,
} from "./workflow-service.js";
import {StorageAreaPort} from "./storage-runtime.js";

export const LEGACY_CURRENT_WORK_KEY = "caldavAssistant.currentWorkId";
export const LEGACY_RUNTIME_KEY = "caldavAssistant.runtime";
export const LEGACY_LAST_RECEIPT_KEY = "caldavAssistant.lastReceipt";
export const LEGACY_AUDIT_KEY = "caldavAssistant.audit";
export const LEGACY_AUDIT_DATES_KEY = "caldavAssistant.auditDates";
export const LEGACY_AUDIT_PREFIX = "caldavAssistant.audit.";

interface LegacyStartEvidence {
  readonly taskId: string;
  readonly startedAt: string;
  readonly receiptId: string;
  readonly beforeStatus: TaskStatus;
  readonly beforePercentComplete: number;
}

export type LegacyActiveMigrationResult =
  | {readonly kind: "none"}
  | {readonly kind: "already-migrated"; readonly taskId: string}
  | {readonly kind: "migrated"; readonly taskId: string; readonly sessionId: string}
  | {readonly kind: "stale-finished"; readonly taskId: string}
  | {readonly kind: "unresolved"; readonly taskId: string | null; readonly message: string};

function object(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? value as Record<string, unknown>
    : null;
}

function nonEmptyText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function validIso(value: unknown): value is string {
  return typeof value === "string" &&
    value.length > 0 &&
    !Number.isNaN(Date.parse(value));
}

function legacyTaskRef(value: unknown): TaskRef | null {
  const item = object(value);
  if (!item) return null;
  const calendarId = nonEmptyText(item.calendarId);
  const uid = nonEmptyText(item.uid) ?? nonEmptyText(item.id);
  if (!calendarId || !uid) return null;
  return Object.freeze({
    calendarId,
    uid,
    recurrenceId:
      typeof item.recurrenceId === "string" ? item.recurrenceId : "",
  });
}

function legacyTaskId(value: unknown): string | null {
  const ref = legacyTaskRef(value);
  return ref ? makeTaskId(ref) : null;
}

function status(value: unknown): TaskStatus | null {
  if (typeof value !== "string") return null;
  const text = value.toUpperCase();
  return text === "" ||
    text === "NEEDS-ACTION" ||
    text === "IN-PROCESS" ||
    text === "COMPLETED" ||
    text === "CANCELLED"
    ? text
    : null;
}

function percent(value: unknown): number | null {
  const number = Number(value);
  return Number.isFinite(number) &&
    Number.isInteger(number) &&
    number >= 0 &&
    number <= 100
    ? number
    : null;
}

function receiptFromRecord(value: unknown): Record<string, unknown> | null {
  const record = object(value);
  if (!record) return null;

  // lastReceipt is the receipt itself. Audit entries wrap that same receipt in
  // details. Accept either shape as migration input only.
  const details = object(record.details);
  if (details && nonEmptyText(details.action)) return details;
  if (nonEmptyText(record.action)) return record;
  return null;
}

function startEvidence(
  value: unknown,
  targetTaskId: string
): LegacyStartEvidence | null {
  const receipt = receiptFromRecord(value);
  if (!receipt) return null;
  if (receipt.action !== "start" || receipt.success !== true) return null;

  const task = object(receipt.task);
  if (!task || legacyTaskId(task) !== targetTaskId) return null;

  const startedAt = receipt.startedAt;
  if (!validIso(startedAt)) return null;

  const beforeStatus = status(task.beforeStatus);
  const beforePercentComplete = percent(task.beforePercentComplete);
  if (
    beforeStatus === null ||
    beforeStatus === "COMPLETED" ||
    beforeStatus === "CANCELLED" ||
    beforePercentComplete === null
  ) {
    return null;
  }

  const receiptId =
    nonEmptyText(receipt.id) ??
    "start-" + String(Date.parse(startedAt));

  return Object.freeze({
    taskId: targetTaskId,
    startedAt,
    receiptId,
    beforeStatus,
    beforePercentComplete,
  });
}

function runtimeEvidence(
  runtimeValue: unknown,
  targetTaskId: string
): LegacyStartEvidence | null {
  const runtime = object(runtimeValue);
  if (!runtime || legacyTaskId(runtime.currentTask) !== targetTaskId) {
    return null;
  }
  const before = object(runtime.taskBeforeStart);
  if (!before) return null;

  const beforeStatus = status(before.status);
  const beforePercentComplete = percent(before.percentComplete);
  const startedAtMs = Number(runtime.segmentStartedAtMs);
  if (
    beforeStatus === null ||
    beforeStatus === "COMPLETED" ||
    beforeStatus === "CANCELLED" ||
    beforePercentComplete === null ||
    !Number.isFinite(startedAtMs) ||
    startedAtMs <= 0
  ) {
    return null;
  }

  return Object.freeze({
    taskId: targetTaskId,
    startedAt: new Date(startedAtMs).toISOString(),
    receiptId: "legacy-runtime-" + Math.trunc(startedAtMs),
    beforeStatus,
    beforePercentComplete,
  });
}

async function legacyRecords(storage: StorageAreaPort): Promise<unknown[]> {
  const base = await storage.get([
    LEGACY_LAST_RECEIPT_KEY,
    LEGACY_AUDIT_KEY,
    LEGACY_AUDIT_DATES_KEY,
  ]);
  const records: unknown[] = [];

  if (base[LEGACY_LAST_RECEIPT_KEY] !== undefined) {
    records.push(base[LEGACY_LAST_RECEIPT_KEY]);
  }
  if (Array.isArray(base[LEGACY_AUDIT_KEY])) {
    records.push(...base[LEGACY_AUDIT_KEY]);
  }

  const dates = Array.isArray(base[LEGACY_AUDIT_DATES_KEY])
    ? base[LEGACY_AUDIT_DATES_KEY].filter(
        value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)
      ) as string[]
    : [];

  if (dates.length) {
    const keys = dates.map(date => LEGACY_AUDIT_PREFIX + date);
    const dated = await storage.get(keys);
    for (const key of keys) {
      const values = dated[key];
      if (Array.isArray(values)) records.push(...values);
    }
  }
  return records;
}

async function findEvidence(
  storage: StorageAreaPort,
  taskId: string,
  runtimeValue: unknown
): Promise<LegacyStartEvidence | null> {
  const candidates: LegacyStartEvidence[] = [];
  for (const record of await legacyRecords(storage)) {
    const evidence = startEvidence(record, taskId);
    if (evidence) candidates.push(evidence);
  }

  const runtime = runtimeEvidence(runtimeValue, taskId);
  if (runtime) candidates.push(runtime);

  candidates.sort(
    (a, b) => Date.parse(b.startedAt) - Date.parse(a.startedAt)
  );
  return candidates[0] ?? null;
}

function pointerFromLegacy(
  storedPointer: unknown,
  runtimeValue: unknown
): string | null {
  // 0.3.16 treats an explicit null pointer as authoritative idle state. Only
  // profiles that never wrote the pointer key may fall back to older runtime.
  if (storedPointer === null) return null;
  if (storedPointer !== undefined) {
    return typeof storedPointer === "string" && parseTaskId(storedPointer)
      ? storedPointer
      : null;
  }
  const runtime = object(runtimeValue);
  return legacyTaskId(runtime?.currentTask);
}

function migrationSession(evidence: LegacyStartEvidence): WorkSession {
  return Object.freeze({
    id: "legacy-" + encodeURIComponent(evidence.receiptId),
    start: evidence.startedAt,
    end: null,
    result: null,
    before: Object.freeze({
      status: evidence.beforeStatus,
      percentComplete: evidence.beforePercentComplete,
    }),
  });
}

/**
 * Convert a single active legacy 0.3.x session into the clean-room VTODO
 * Description format.
 *
 * No old runtime/audit field is used after this function returns. Cleanup is a
 * separate finalization step so an interrupted migration never destroys its
 * own recovery evidence.
 */
export async function migrateLegacyActiveSession(
  storage: StorageAreaPort,
  tasks: ThunderbirdTaskPort,
  currentWork: CurrentWorkPort
): Promise<LegacyActiveMigrationResult> {
  if ((await currentWork.getCurrentWorkId()) !== null) {
    return {kind: "none"};
  }

  const values = await storage.get([
    LEGACY_CURRENT_WORK_KEY,
    LEGACY_RUNTIME_KEY,
  ]);
  const runtimeValue = values[LEGACY_RUNTIME_KEY];
  const taskId = pointerFromLegacy(
    values[LEGACY_CURRENT_WORK_KEY],
    runtimeValue
  );
  if (!taskId) return {kind: "none"};

  const ref = parseTaskId(taskId);
  if (!ref) {
    return {
      kind: "unresolved",
      taskId,
      message: "Legacy currentWorkId is invalid.",
    };
  }

  let task: TaskSnapshot;
  try {
    task = await tasks.getTask(ref);
  } catch (error) {
    return {
      kind: "unresolved",
      taskId,
      message:
        "Legacy active VTODO could not be read: " +
        (error instanceof Error ? error.message : String(error)),
    };
  }

  if (task.status === "COMPLETED" || task.status === "CANCELLED") {
    return {kind: "stale-finished", taskId};
  }

  const parsed = parseWorkDescription(task.description);
  if (!parsed.ok) {
    return {
      kind: "unresolved",
      taskId,
      message:
        "Legacy active VTODO Description already contains an invalid Assistant block: " +
        parsed.reason,
    };
  }

  const alreadyOpen = getOpenSession(parsed);
  if (alreadyOpen) {
    await currentWork.setCurrentWorkId(taskId);
    if ((await currentWork.getCurrentWorkId()) !== taskId) {
      return {
        kind: "unresolved",
        taskId,
        message: "Migrated currentWorkId read-back failed.",
      };
    }
    return {kind: "already-migrated", taskId};
  }

  const evidence = await findEvidence(storage, taskId, runtimeValue);
  if (!evidence) {
    return {
      kind: "unresolved",
      taskId,
      message:
        "No trustworthy legacy Start timestamp/pre-Start Task state was found; legacy data was left untouched.",
    };
  }

  const session = migrationSession(evidence);
  const opened = openWorkSession(parsed, session);
  if (!opened) {
    return {
      kind: "unresolved",
      taskId,
      message: "Could not construct a legacy migration session.",
    };
  }
  const description = serializeWorkDescription(opened);

  try {
    await tasks.updateTask(ref, {description});
    const stored = await tasks.getTask(ref);
    const verified = parseWorkDescription(stored.description);
    if (
      !verified.ok ||
      getOpenSession(verified)?.id !== session.id
    ) {
      return {
        kind: "unresolved",
        taskId,
        message: "Migrated VTODO Description read-back failed.",
      };
    }

    await currentWork.setCurrentWorkId(taskId);
    if ((await currentWork.getCurrentWorkId()) !== taskId) {
      return {
        kind: "unresolved",
        taskId,
        message: "Migrated currentWorkId read-back failed.",
      };
    }
  } catch (error) {
    return {
      kind: "unresolved",
      taskId,
      message:
        "Legacy active-session migration failed: " +
        (error instanceof Error ? error.message : String(error)),
    };
  }

  return {
    kind: "migrated",
    taskId,
    sessionId: session.id,
  };
}
