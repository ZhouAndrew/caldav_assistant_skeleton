import {
  TaskPatch,
  TaskRef,
  TaskSnapshot,
  WorkIntent,
  WorkSession,
} from "./domain";
import {makeTaskId, parseTaskId} from "./task-id";
import {getOpenSession, parseWorkDescription} from "./work-description";
import {planTaskAction} from "./workflow";

export interface ThunderbirdTaskPort {
  getTask(ref: TaskRef): Promise<TaskSnapshot>;
  updateTask(ref: TaskRef, patch: TaskPatch): Promise<TaskSnapshot>;
}

export interface CurrentWorkPort {
  getCurrentWorkId(): Promise<string | null>;
  setCurrentWorkId(value: string | null): Promise<void>;
}

export interface WorkflowDependencies {
  readonly tasks: ThunderbirdTaskPort;
  readonly currentWork: CurrentWorkPort;
  readonly nowIso: () => string;
  readonly newSessionId: () => string;
}

export type CommitState = "not-committed" | "committed" | "unknown";

export type TaskCommandResult =
  | {
      readonly kind: "committed";
      readonly intent: WorkIntent;
      readonly task: TaskSnapshot;
      readonly closedSession: WorkSession | null;
    }
  | {
      readonly kind: "rejected";
      readonly intent: WorkIntent;
      readonly reason: string;
    }
  | {
      readonly kind: "failed";
      readonly intent: WorkIntent;
      readonly commitState: CommitState;
      readonly message: string;
    }
  | {
      readonly kind: "recovery-required";
      readonly intent: WorkIntent;
      readonly commitState: CommitState;
      readonly message: string;
    };

export type ReconcileResult =
  | {readonly kind: "idle"}
  | {readonly kind: "valid"; readonly taskId: string; readonly task: TaskSnapshot}
  | {readonly kind: "cleared-stale-pointer"; readonly previousTaskId: string}
  | {readonly kind: "unresolved"; readonly taskId: string; readonly message: string};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function patchMatches(task: TaskSnapshot, patch: TaskPatch): boolean {
  if (task.description !== patch.description) return false;
  if (patch.status !== undefined && task.status !== patch.status) return false;
  if (
    patch.percentComplete !== undefined &&
    task.percentComplete !== patch.percentComplete
  ) {
    return false;
  }
  return true;
}

async function readCurrentExactly(
  currentWork: CurrentWorkPort,
  expected: string | null
): Promise<boolean> {
  return (await currentWork.getCurrentWorkId()) === expected;
}

async function writeAndVerify(
  tasks: ThunderbirdTaskPort,
  ref: TaskRef,
  patch: TaskPatch
): Promise<
  | {kind: "verified"; task: TaskSnapshot}
  | {kind: "mismatch"; task: TaskSnapshot; writeError: string | null}
  | {kind: "unknown"; writeError: string | null; readError: string}
> {
  let writeError: string | null = null;
  try {
    await tasks.updateTask(ref, patch);
  } catch (error) {
    writeError = errorText(error);
  }

  try {
    const stored = await tasks.getTask(ref);
    if (patchMatches(stored, patch)) {
      return {kind: "verified", task: stored};
    }
    return {kind: "mismatch", task: stored, writeError};
  } catch (error) {
    return {
      kind: "unknown",
      writeError,
      readError: errorText(error),
    };
  }
}

async function reserveCurrentPointer(
  currentWork: CurrentWorkPort,
  taskId: string
): Promise<string | null> {
  try {
    await currentWork.setCurrentWorkId(taskId);
    if (!(await readCurrentExactly(currentWork, taskId))) {
      return "currentWorkId read-back mismatch after reservation";
    }
    return null;
  } catch (error) {
    return errorText(error);
  }
}

async function clearCurrentPointer(
  currentWork: CurrentWorkPort
): Promise<string | null> {
  try {
    await currentWork.setCurrentWorkId(null);
    if (!(await readCurrentExactly(currentWork, null))) {
      return "currentWorkId read-back mismatch after clear";
    }
    return null;
  } catch (error) {
    return errorText(error);
  }
}

export async function executeTaskCommand(
  intent: WorkIntent,
  taskId: string,
  deps: WorkflowDependencies
): Promise<TaskCommandResult> {
  const ref = parseTaskId(taskId);
  if (!ref) {
    return {kind: "rejected", intent, reason: "invalid-task-id"};
  }

  let task: TaskSnapshot;
  let currentWorkId: string | null;
  try {
    task = await deps.tasks.getTask(ref);
    currentWorkId = await deps.currentWork.getCurrentWorkId();
  } catch (error) {
    return {
      kind: "failed",
      intent,
      commitState: "not-committed",
      message: errorText(error),
    };
  }

  const plan = planTaskAction(
    intent,
    task,
    currentWorkId,
    deps.nowIso(),
    intent === "start" ? deps.newSessionId() : ""
  );
  if (!plan.ok) {
    return {kind: "rejected", intent, reason: plan.reason};
  }

  if (intent === "start") {
    // Reserve the one local pointer before opening the durable VTODO session.
    // A crash here leaves only a stale pointer; reconcileCurrentWork() can
    // safely clear it because the Task Description still has no open session.
    const reserveError = await reserveCurrentPointer(deps.currentWork, taskId);
    if (reserveError) {
      return {
        kind: "failed",
        intent,
        commitState: "not-committed",
        message: "Could not reserve currentWorkId: " + reserveError,
      };
    }

    const written = await writeAndVerify(deps.tasks, ref, plan.taskPatch);
    if (written.kind === "verified") {
      return {
        kind: "committed",
        intent,
        task: written.task,
        closedSession: null,
      };
    }

    if (written.kind === "unknown") {
      return {
        kind: "recovery-required",
        intent,
        commitState: "unknown",
        message:
          "VTODO write outcome could not be verified; currentWorkId is intentionally retained. " +
          [written.writeError, written.readError].filter(Boolean).join(" | "),
      };
    }

    const clearError = await clearCurrentPointer(deps.currentWork);
    if (clearError) {
      return {
        kind: "recovery-required",
        intent,
        commitState: "not-committed",
        message:
          "VTODO did not match the planned Start and the reserved pointer could not be cleared: " +
          clearError,
      };
    }
    return {
      kind: "failed",
      intent,
      commitState: "not-committed",
      message:
        "VTODO did not match the planned Start." +
        (written.writeError ? " " + written.writeError : ""),
    };
  }

  // Closing actions commit and verify the VTODO first. Only then is the local
  // pointer cleared. A crash between these steps leaves a stale pointer to a
  // Task whose Description contains no open session, which is safe to repair.
  const written = await writeAndVerify(deps.tasks, ref, plan.taskPatch);
  if (written.kind === "unknown") {
    return {
      kind: "recovery-required",
      intent,
      commitState: "unknown",
      message:
        "VTODO close outcome could not be verified; currentWorkId is retained. " +
        [written.writeError, written.readError].filter(Boolean).join(" | "),
    };
  }
  if (written.kind === "mismatch") {
    return {
      kind: "failed",
      intent,
      commitState: "not-committed",
      message:
        "VTODO read-back did not match the planned " +
        intent +
        "." +
        (written.writeError ? " " + written.writeError : ""),
    };
  }

  const clearError = await clearCurrentPointer(deps.currentWork);
  if (clearError) {
    return {
      kind: "recovery-required",
      intent,
      commitState: "committed",
      message:
        "VTODO transition is committed but currentWorkId could not be cleared: " +
        clearError,
    };
  }

  return {
    kind: "committed",
    intent,
    task: written.task,
    closedSession: plan.closedSession,
  };
}

export async function reconcileCurrentWork(
  deps: Pick<WorkflowDependencies, "tasks" | "currentWork">
): Promise<ReconcileResult> {
  let taskId: string | null;
  try {
    taskId = await deps.currentWork.getCurrentWorkId();
  } catch (error) {
    return {
      kind: "unresolved",
      taskId: "",
      message: "Could not read currentWorkId: " + errorText(error),
    };
  }
  if (taskId === null) return {kind: "idle"};

  const ref = parseTaskId(taskId);
  if (!ref) {
    const clearError = await clearCurrentPointer(deps.currentWork);
    return clearError
      ? {
          kind: "unresolved",
          taskId,
          message: "Invalid currentWorkId and clear failed: " + clearError,
        }
      : {kind: "cleared-stale-pointer", previousTaskId: taskId};
  }

  let task: TaskSnapshot;
  try {
    task = await deps.tasks.getTask(ref);
  } catch (error) {
    return {
      kind: "unresolved",
      taskId,
      message: "Current VTODO could not be read: " + errorText(error),
    };
  }

  const parsed = parseWorkDescription(task.description);
  if (!parsed.ok) {
    return {
      kind: "unresolved",
      taskId,
      message: "Current VTODO Description work-log is corrupt: " + parsed.reason,
    };
  }

  if (getOpenSession(parsed)) {
    if (makeTaskId(task) !== taskId) {
      return {
        kind: "unresolved",
        taskId,
        message: "Current VTODO identity no longer matches currentWorkId.",
      };
    }
    return {kind: "valid", taskId, task};
  }

  const clearError = await clearCurrentPointer(deps.currentWork);
  return clearError
    ? {
        kind: "unresolved",
        taskId,
        message: "Stale currentWorkId could not be cleared: " + clearError,
      }
    : {kind: "cleared-stale-pointer", previousTaskId: taskId};
}
