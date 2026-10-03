import {
  TaskRef,
  WorkSession,
} from "./domain";
import {
  classifyPersistedPointer,
  findLegacyStartFact,
} from "./legacy-migration";
import {
  TaskPort,
  TaskPrecondition,
  TaskRecord,
} from "./ports";
import {
  openSession,
  openSessions,
  parseWorkDescription,
  serializeWorkDescription,
} from "./work-description";

export interface LegacyMigrationStore {
  isComplete(): Promise<boolean>;
  getRawCurrentWorkId(): Promise<unknown>;
  getLegacyRuntime(): Promise<unknown>;
  getLastReceipt(): Promise<unknown>;
  listAuditRecords(): Promise<readonly unknown[]>;
  setCurrentWorkId(value: string | null): Promise<void>;
  removeLegacyRuntime(): Promise<void>;
  markComplete(): Promise<void>;
}

export type LegacyMigrationResult =
  | Readonly<{
      ok: true;
      state: "already-complete" | "idle" | "migrated";
      currentWorkId: string | null;
      source?: "last-receipt" | "audit" | "legacy-runtime" | "existing-worklog";
    }>
  | Readonly<{
      ok: false;
      state: "blocked";
      reason:
        | "invalid-pointer"
        | "task-unreadable"
        | "description-invalid"
        | "multiple-open-sessions"
        | "start-fact-missing"
        | "task-changed"
        | "task-not-writable"
        | "read-back-mismatch"
        | "pointer-write-failed"
        | "cleanup-failed";
      currentWorkId: string | null;
    }>;

export interface LegacyMigrationDependencies {
  readonly tasks: Pick<TaskPort, "getTask" | "updateTask">;
  readonly store: LegacyMigrationStore;
  readonly newSessionId: () => string;
  readonly staleWriteRetries?: number;
}

function precondition(task: TaskRecord): TaskPrecondition {
  return Object.freeze({
    status: task.status,
    completed: task.completed,
    percentComplete: task.percentComplete,
    description: task.description,
  });
}

async function finishMigration(
  store: LegacyMigrationStore,
  currentWorkId: string | null,
  source?: "last-receipt" | "audit" | "legacy-runtime" | "existing-worklog",
): Promise<LegacyMigrationResult> {
  try {
    await store.removeLegacyRuntime();
    await store.markComplete();
  } catch {
    return Object.freeze({
      ok: false,
      state: "blocked",
      reason: "cleanup-failed",
      currentWorkId,
    });
  }

  return Object.freeze({
    ok: true,
    state: currentWorkId ? "migrated" : "idle",
    currentWorkId,
    ...(source ? {source} : {}),
  });
}

async function publishPointer(
  store: LegacyMigrationStore,
  id: string,
): Promise<boolean> {
  try {
    await store.setCurrentWorkId(id);
    return true;
  } catch {
    return false;
  }
}

export async function migrateLegacyState(
  dependencies: LegacyMigrationDependencies,
): Promise<LegacyMigrationResult> {
  if (await dependencies.store.isComplete()) {
    const raw = await dependencies.store.getRawCurrentWorkId();
    return Object.freeze({
      ok: true,
      state: "already-complete",
      currentWorkId: typeof raw === "string" && raw ? raw : null,
    });
  }

  const rawPointer = await dependencies.store.getRawCurrentWorkId();
  const runtime = await dependencies.store.getLegacyRuntime();
  const pointer = classifyPersistedPointer(rawPointer, runtime);

  if (pointer.kind === "invalid") {
    return Object.freeze({
      ok: false,
      state: "blocked",
      reason: "invalid-pointer",
      currentWorkId: pointer.raw,
    });
  }

  if (pointer.kind === "none") {
    return finishMigration(dependencies.store, null);
  }

  if (pointer.kind === "new") {
    // A clean-room pointer already exists. Only remove obsolete runtime data.
    return finishMigration(dependencies.store, pointer.id);
  }

  let task: TaskRecord;
  try {
    task = await dependencies.tasks.getTask(pointer.ref);
  } catch {
    return Object.freeze({
      ok: false,
      state: "blocked",
      reason: "task-unreadable",
      currentWorkId:
        typeof rawPointer === "string" && rawPointer ? rawPointer : null,
    });
  }

  const firstParsed = parseWorkDescription(task.description);
  if (!firstParsed.ok) {
    return Object.freeze({
      ok: false,
      state: "blocked",
      reason: "description-invalid",
      currentWorkId:
        typeof rawPointer === "string" && rawPointer ? rawPointer : null,
    });
  }

  const existingOpen = openSessions(firstParsed.value);
  if (existingOpen.length > 1) {
    return Object.freeze({
      ok: false,
      state: "blocked",
      reason: "multiple-open-sessions",
      currentWorkId:
        typeof rawPointer === "string" && rawPointer ? rawPointer : null,
    });
  }

  if (existingOpen.length === 1) {
    if (!(await publishPointer(dependencies.store, pointer.id))) {
      return Object.freeze({
        ok: false,
        state: "blocked",
        reason: "pointer-write-failed",
        currentWorkId:
          typeof rawPointer === "string" && rawPointer ? rawPointer : null,
      });
    }
    return finishMigration(
      dependencies.store,
      pointer.id,
      "existing-worklog",
    );
  }

  const lastReceipt = await dependencies.store.getLastReceipt();
  const auditRecords = await dependencies.store.listAuditRecords();
  const fact = findLegacyStartFact({
    ref: pointer.ref,
    lastReceipt,
    auditRecords,
    runtime,
  });

  if (!fact) {
    return Object.freeze({
      ok: false,
      state: "blocked",
      reason: "start-fact-missing",
      currentWorkId:
        typeof rawPointer === "string" && rawPointer ? rawPointer : null,
    });
  }

  const retryLimit = Math.max(
    0,
    Math.min(3, Math.trunc(dependencies.staleWriteRetries ?? 1)),
  );
  const sessionId = dependencies.newSessionId();

  for (let attempt = 0; attempt <= retryLimit; attempt++) {
    if (attempt > 0) {
      try {
        task = await dependencies.tasks.getTask(pointer.ref);
      } catch {
        return Object.freeze({
          ok: false,
          state: "blocked",
          reason: "task-unreadable",
          currentWorkId:
            typeof rawPointer === "string" && rawPointer ? rawPointer : null,
        });
      }
    }

    const parsed = parseWorkDescription(task.description);
    if (!parsed.ok) {
      return Object.freeze({
        ok: false,
        state: "blocked",
        reason: "description-invalid",
        currentWorkId:
          typeof rawPointer === "string" && rawPointer ? rawPointer : null,
      });
    }

    const open = openSessions(parsed.value);
    if (open.length > 1) {
      return Object.freeze({
        ok: false,
        state: "blocked",
        reason: "multiple-open-sessions",
        currentWorkId:
          typeof rawPointer === "string" && rawPointer ? rawPointer : null,
      });
    }

    if (open.length === 1) {
      break;
    }

    const session: WorkSession = Object.freeze({
      id: sessionId,
      start: fact.start,
      end: null,
      result: null,
      before: Object.freeze({status: fact.beforeStatus}),
    });
    const next = openSession(parsed.value, session);
    if (!next) {
      return Object.freeze({
        ok: false,
        state: "blocked",
        reason: "multiple-open-sessions",
        currentWorkId:
          typeof rawPointer === "string" && rawPointer ? rawPointer : null,
      });
    }

    const expectedDescription = serializeWorkDescription(next);
    const written = await dependencies.tasks.updateTask(
      pointer.ref,
      {description: expectedDescription},
      precondition(task),
    );

    if (!written.ok) {
      if (written.reason === "changed" && attempt < retryLimit) continue;
      return Object.freeze({
        ok: false,
        state: "blocked",
        reason:
          written.reason === "changed"
            ? "task-changed"
            : "task-not-writable",
        currentWorkId:
          typeof rawPointer === "string" && rawPointer ? rawPointer : null,
      });
    }

    if (written.task.description !== expectedDescription) {
      return Object.freeze({
        ok: false,
        state: "blocked",
        reason: "read-back-mismatch",
        currentWorkId:
          typeof rawPointer === "string" && rawPointer ? rawPointer : null,
      });
    }

    task = written.task;
    break;
  }

  const finalParsed = parseWorkDescription(task.description);
  if (!finalParsed.ok || openSessions(finalParsed.value).length !== 1) {
    return Object.freeze({
      ok: false,
      state: "blocked",
      reason: "read-back-mismatch",
      currentWorkId:
        typeof rawPointer === "string" && rawPointer ? rawPointer : null,
    });
  }

  if (!(await publishPointer(dependencies.store, pointer.id))) {
    return Object.freeze({
      ok: false,
      state: "blocked",
      reason: "pointer-write-failed",
      currentWorkId:
        typeof rawPointer === "string" && rawPointer ? rawPointer : null,
    });
  }

  return finishMigration(
    dependencies.store,
    pointer.id,
    fact.source,
  );
}
