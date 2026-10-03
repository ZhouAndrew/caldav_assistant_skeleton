import {
  StoredTaskStatus,
  TaskRef,
  parseTaskId,
  taskId,
} from "./domain";

export interface LegacyStartFact {
  readonly ref: TaskRef;
  readonly start: string;
  readonly beforeStatus: StoredTaskStatus;
  readonly source: "last-receipt" | "audit" | "legacy-runtime";
}

function nonEmpty(value: unknown): string | null {
  return typeof value === "string" && value.length ? value : null;
}

function validIso(value: unknown): string | null {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) {
    return null;
  }
  return new Date(value).toISOString();
}

function storedStatus(value: unknown): StoredTaskStatus {
  if (value === null || value === undefined || value === "") return null;
  const status = String(value).toUpperCase();
  if (
    status === "NEEDS-ACTION" ||
    status === "IN-PROCESS" ||
    status === "COMPLETED" ||
    status === "CANCELLED"
  ) {
    return status;
  }
  return null;
}

export function parseLegacyTaskId(value: unknown): TaskRef | null {
  if (typeof value !== "string") return null;
  const parts = value.split("|");
  if (parts.length !== 3) return null;

  try {
    const calendarId = decodeURIComponent(parts[0] ?? "");
    const uid = decodeURIComponent(parts[1] ?? "");
    const recurrenceId = decodeURIComponent(parts[2] ?? "");
    if (!calendarId || !uid) return null;
    return Object.freeze({calendarId, uid, recurrenceId});
  } catch {
    return null;
  }
}

export function legacyRuntimeRef(value: unknown): TaskRef | null {
  if (!value || typeof value !== "object") return null;
  const runtime = value as Record<string, unknown>;
  const current = runtime.currentTask;
  if (!current || typeof current !== "object") return null;
  const task = current as Record<string, unknown>;
  const calendarId = nonEmpty(task.calendarId);
  const uid = nonEmpty(task.id);
  if (!calendarId || !uid) return null;
  return Object.freeze({
    calendarId,
    uid,
    recurrenceId:
      typeof task.recurrenceId === "string" ? task.recurrenceId : "",
  });
}

export type PersistedPointer =
  | Readonly<{kind: "none"}>
  | Readonly<{kind: "new"; ref: TaskRef; id: string}>
  | Readonly<{kind: "legacy"; ref: TaskRef; id: string}>
  | Readonly<{kind: "invalid"; raw: string}>;

export function classifyPersistedPointer(
  raw: unknown,
  runtime: unknown,
): PersistedPointer {
  if (typeof raw === "string" && raw) {
    const modern = parseTaskId(raw);
    if (modern) {
      return Object.freeze({kind: "new", ref: modern, id: raw});
    }

    const legacy = parseLegacyTaskId(raw);
    if (legacy) {
      return Object.freeze({
        kind: "legacy",
        ref: legacy,
        id: taskId(legacy),
      });
    }

    return Object.freeze({kind: "invalid", raw});
  }

  const legacy = legacyRuntimeRef(runtime);
  if (legacy) {
    return Object.freeze({
      kind: "legacy",
      ref: legacy,
      id: taskId(legacy),
    });
  }

  return Object.freeze({kind: "none"});
}

function refFromReceiptTask(value: unknown): TaskRef | null {
  if (!value || typeof value !== "object") return null;
  const task = value as Record<string, unknown>;
  const calendarId = nonEmpty(task.calendarId);
  const uid = nonEmpty(task.id);
  if (!calendarId || !uid) return null;
  return Object.freeze({
    calendarId,
    uid,
    recurrenceId:
      typeof task.recurrenceId === "string" ? task.recurrenceId : "",
  });
}

function sameRef(a: TaskRef | null, b: TaskRef): boolean {
  return Boolean(a && taskId(a) === taskId(b));
}

function receiptFact(
  raw: unknown,
  ref: TaskRef,
  source: LegacyStartFact["source"],
  fallbackTimestamp: unknown = null,
): LegacyStartFact | null {
  if (!raw || typeof raw !== "object") return null;
  const receipt = raw as Record<string, unknown>;

  if (receipt.action !== undefined && receipt.action !== "start") return null;
  if (receipt.success === false) return null;

  const receiptRef = refFromReceiptTask(receipt.task);
  if (!sameRef(receiptRef, ref)) return null;

  const start = validIso(receipt.startedAt) ?? validIso(fallbackTimestamp);
  if (!start) return null;

  const task = receipt.task as Record<string, unknown>;
  return Object.freeze({
    ref,
    start,
    beforeStatus: storedStatus(task.beforeStatus),
    source,
  });
}

export function findLegacyStartFact(args: {
  readonly ref: TaskRef;
  readonly lastReceipt?: unknown;
  readonly auditRecords?: readonly unknown[];
  readonly runtime?: unknown;
}): LegacyStartFact | null {
  const direct = receiptFact(args.lastReceipt, args.ref, "last-receipt");
  if (direct) return direct;

  const records = args.auditRecords ?? [];
  for (let index = records.length - 1; index >= 0; index--) {
    const raw = records[index];
    if (!raw || typeof raw !== "object") continue;
    const record = raw as Record<string, unknown>;
    if (record.scope !== "workflow" || record.action !== "start") continue;
    if (record.success === false) continue;

    const fact = receiptFact(
      record.details,
      args.ref,
      "audit",
      record.timestamp,
    );
    if (fact) return fact;
  }

  if (args.runtime && typeof args.runtime === "object") {
    const runtime = args.runtime as Record<string, unknown>;
    if (sameRef(legacyRuntimeRef(runtime), args.ref)) {
      const at = Number(runtime.segmentStartedAtMs);
      if (Number.isFinite(at) && at > 0) {
        const before = runtime.taskBeforeStart;
        const beforeStatus =
          before && typeof before === "object"
            ? storedStatus((before as Record<string, unknown>).status)
            : null;
        return Object.freeze({
          ref: args.ref,
          start: new Date(at).toISOString(),
          beforeStatus,
          source: "legacy-runtime",
        });
      }
    }
  }

  return null;
}
