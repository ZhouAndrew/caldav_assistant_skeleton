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

  async function execute(
    intent: WorkIntent,
    ref: TaskRef,
  ): Promise<WorkflowServiceResult> {
    const now = dependencies.now();
    const sessionId =
      intent === "start" ? dependencies.newSessionId() : undefined;

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
        return Object.freeze({
          ok: false,
          intent,
          reason: plan.reason,
          committed: false,
        });
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

      try {
        await dependencies.currentWork.set(plan.nextCurrentWorkId);
      } catch {
        // The VTODO is already durably committed.  Do not roll it back; startup
        // reconciliation repairs the pointer from the Description work-log.
        return Object.freeze({
          ok: false,
          intent,
          reason: "pointer-write-failed",
          committed: true,
        });
      }

      return Object.freeze({
        ok: true,
        intent,
        task: written.task,
        closedSession: plan.closedSession,
      });
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
