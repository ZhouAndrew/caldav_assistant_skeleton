import {
  PlanRejection,
  TaskPatch,
  TaskRef,
  WorkIntent,
  WorkSession,
} from "./domain";
import {
  TaskPort,
  TaskPrecondition,
  TaskRecord,
} from "./ports";
import {planTaskAction} from "./workflow";

export interface CurrentWorkStore {
  get(): Promise<string | null>;
  set(value: string | null): Promise<void>;
}

export type WorkflowFailureReason =
  | PlanRejection
  | "changed"
  | "not-writable"
  | "read-back-mismatch"
  | "pointer-write-failed";

export type WorkflowServiceResult =
  | Readonly<{
      ok: true;
      intent: WorkIntent;
      task: TaskRecord;
      closedSession: WorkSession | null;
    }>
  | Readonly<{
      ok: false;
      intent: WorkIntent;
      reason: WorkflowFailureReason;
      committed: boolean;
    }>;

export interface TaskWorkflowService {
  start(ref: TaskRef): Promise<WorkflowServiceResult>;
  stop(ref: TaskRef): Promise<WorkflowServiceResult>;
  complete(ref: TaskRef): Promise<WorkflowServiceResult>;
  cancel(ref: TaskRef): Promise<WorkflowServiceResult>;
}

export interface WorkflowDependencies {
  readonly tasks: TaskPort;
  readonly currentWork: CurrentWorkStore;
  readonly now: () => string;
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

function patchMatches(task: TaskRecord, patch: Readonly<TaskPatch>): boolean {
  if ("status" in patch && task.status !== patch.status) return false;
  if (
    "percentComplete" in patch &&
    task.percentComplete !== patch.percentComplete
  ) {
    return false;
  }
  if ("description" in patch && task.description !== patch.description) {
    return false;
  }
  return true;
}

export function createTaskWorkflowService(
  dependencies: WorkflowDependencies,
): TaskWorkflowService {
  const retryLimit = Math.max(
    0,
    Math.min(3, Math.trunc(dependencies.staleWriteRetries ?? 1)),
  );

  // All workflow commands in one background context are serialized.  This keeps
  // two pages/double-clicks from observing currentWorkId=null simultaneously.
  let tail: Promise<void> = Promise.resolve();

  function enqueue(
    run: () => Promise<WorkflowServiceResult>,
  ): Promise<WorkflowServiceResult> {
    const result = tail.then(run, run);
    tail = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }

  async function pointerFailure(
    intent: WorkIntent,
    committed: boolean,
  ): Promise<WorkflowServiceResult> {
    return Object.freeze({
      ok: false,
      intent,
      reason: "pointer-write-failed",
      committed,
    });
  }

  async function clearStartReservation(
    intent: WorkIntent,
    reason: WorkflowFailureReason,
  ): Promise<WorkflowServiceResult> {
    try {
      await dependencies.currentWork.set(null);
    } catch {
      return pointerFailure(intent, false);
    }
    return Object.freeze({
      ok: false,
      intent,
      reason,
      committed: false,
    });
  }

  async function execute(
    intent: WorkIntent,
    ref: TaskRef,
  ): Promise<WorkflowServiceResult> {
    const now = dependencies.now();
    const sessionId =
      intent === "start" ? dependencies.newSessionId() : undefined;
    let startReserved = false;

    for (let attempt = 0; attempt <= retryLimit; attempt++) {
      const task = await dependencies.tasks.getTask(ref);
      const currentWorkId = await dependencies.currentWork.get();
      const plan = planTaskAction({
        intent,
        task,
        currentWorkId,
        now,
        ...(sessionId ? {sessionId} : {}),
      });

      if (!plan.ok) {
        if (intent === "start" && startReserved) {
          // If an open session appeared after our reservation, a Task commit
          // may have happened despite a lost response. Keep the pointer so
          // reconciliation can validate it instead of orphaning the session.
          if (plan.reason === "open-session-exists") {
            return Object.freeze({
              ok: false,
              intent,
              reason: plan.reason,
              committed: true,
            });
          }
          return clearStartReservation(intent, plan.reason);
        }
        return Object.freeze({
          ok: false,
          intent,
          reason: plan.reason,
          committed: false,
        });
      }

      if (intent === "start" && !startReserved) {
        if (currentWorkId === null) {
          try {
            await dependencies.currentWork.set(plan.nextCurrentWorkId);
          } catch {
            return pointerFailure(intent, false);
          }
        }
        startReserved = true;
      }

      const written = await dependencies.tasks.updateTask(
        ref,
        plan.taskPatch,
        precondition(task),
      );

      if (!written.ok) {
        if (written.reason === "changed" && attempt < retryLimit) {
          continue;
        }
        if (intent === "start" && startReserved) {
          return clearStartReservation(intent, written.reason);
        }
        return Object.freeze({
          ok: false,
          intent,
          reason: written.reason,
          committed: false,
        });
      }

      if (!patchMatches(written.task, plan.taskPatch)) {
        return Object.freeze({
          ok: false,
          intent,
          reason: "read-back-mismatch",
          committed: true,
        });
      }

      if (intent !== "start") {
        try {
          await dependencies.currentWork.set(plan.nextCurrentWorkId);
        } catch {
          // The VTODO close/final state is already durable. Reconciliation
          // clears the stale pointer from the now-closed Description session.
          return pointerFailure(intent, true);
        }
      }

      return Object.freeze({
        ok: true,
        intent,
        task: written.task,
        closedSession: plan.closedSession,
      });
    }

    if (intent === "start" && startReserved) {
      return clearStartReservation(intent, "changed");
    }

    return Object.freeze({
      ok: false,
      intent,
      reason: "changed",
      committed: false,
    });
  }

  return Object.freeze({
    start: (ref: TaskRef) => enqueue(() => execute("start", ref)),
    stop: (ref: TaskRef) => enqueue(() => execute("stop", ref)),
    complete: (ref: TaskRef) => enqueue(() => execute("complete", ref)),
    cancel: (ref: TaskRef) => enqueue(() => execute("cancel", ref)),
  });
}
