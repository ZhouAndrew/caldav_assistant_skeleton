import {
  TaskRef,
  TaskSnapshot,
  parseTaskId,
  taskId,
} from "./domain";
import {TaskPort} from "./ports";
import {openSessions, parseWorkDescription} from "./work-description";
import {CurrentWorkStore} from "./workflow-service";

export type PointerDecision =
  | Readonly<{kind: "keep"; currentWorkId: string}>
  | Readonly<{kind: "clear"; reason: "no-open-session" | "invalid-pointer"}>
  | Readonly<{
      kind: "blocked";
      reason:
        | "identity-mismatch"
        | "description-invalid"
        | "multiple-open-sessions";
    }>;

export type ReconciliationResult =
  | Readonly<{
      ok: true;
      state: "idle" | "active" | "cleared-stale";
      currentWorkId: string | null;
    }>
  | Readonly<{
      ok: false;
      state: "blocked";
      reason:
        | "task-unreadable"
        | "identity-mismatch"
        | "description-invalid"
        | "multiple-open-sessions"
        | "pointer-write-failed";
      currentWorkId: string;
    }>;

export function decidePointer(
  currentWorkId: string,
  task: TaskSnapshot,
): PointerDecision {
  const ref = parseTaskId(currentWorkId);
  if (!ref) {
    return Object.freeze({kind: "clear", reason: "invalid-pointer"});
  }

  if (taskId(task) !== currentWorkId) {
    return Object.freeze({kind: "blocked", reason: "identity-mismatch"});
  }

  const parsed = parseWorkDescription(task.description);
  if (!parsed.ok) {
    return Object.freeze({kind: "blocked", reason: "description-invalid"});
  }

  const open = openSessions(parsed.value);
  if (open.length === 0) {
    return Object.freeze({kind: "clear", reason: "no-open-session"});
  }
  if (open.length > 1) {
    return Object.freeze({
      kind: "blocked",
      reason: "multiple-open-sessions",
    });
  }

  return Object.freeze({kind: "keep", currentWorkId});
}

async function clearPointer(
  store: CurrentWorkStore,
  previous: string,
): Promise<ReconciliationResult> {
  try {
    await store.set(null);
    return Object.freeze({
      ok: true,
      state: "cleared-stale",
      currentWorkId: null,
    });
  } catch {
    return Object.freeze({
      ok: false,
      state: "blocked",
      reason: "pointer-write-failed",
      currentWorkId: previous,
    });
  }
}

export async function reconcileCurrentWork(
  tasks: Pick<TaskPort, "getTask">,
  store: CurrentWorkStore,
): Promise<ReconciliationResult> {
  const currentWorkId = await store.get();
  if (currentWorkId === null) {
    // New Start reserves the pointer before the VTODO write. Therefore a normal
    // crash cannot create a valid open session without a pointer, and startup
    // does not need an unbounded scan of recurring Tasks.
    return Object.freeze({
      ok: true,
      state: "idle",
      currentWorkId: null,
    });
  }

  const ref: TaskRef | null = parseTaskId(currentWorkId);
  if (!ref) {
    return clearPointer(store, currentWorkId);
  }

  let task;
  try {
    task = await tasks.getTask(ref);
  } catch {
    // Calendar/provider failures can be temporary. Never clear the only pointer
    // merely because its Task could not be read during this startup.
    return Object.freeze({
      ok: false,
      state: "blocked",
      reason: "task-unreadable",
      currentWorkId,
    });
  }

  const decision = decidePointer(currentWorkId, task);
  if (decision.kind === "keep") {
    return Object.freeze({
      ok: true,
      state: "active",
      currentWorkId,
    });
  }
  if (decision.kind === "clear") {
    return clearPointer(store, currentWorkId);
  }

  return Object.freeze({
    ok: false,
    state: "blocked",
    reason: decision.reason,
    currentWorkId,
  });
}
