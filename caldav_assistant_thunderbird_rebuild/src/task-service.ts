import {
  PlanRejection,
  RejectedPlan,
  TaskRef,
  WorkIntent,
  WorkSession,
} from "./domain";
import {
  TaskPort,
  TaskPrecondition,
  TaskRecord,
  TaskWriteResult,
} from "./ports";
import {planTaskAction} from "./workflow";

export interface CurrentWorkPort {
  getCurrentWorkId(): Promise<string | null>;
  setCurrentWorkId(value: string | null): Promise<string | null>;
}

export interface TaskWorkflowPorts {
  readonly tasks: TaskPort;
  readonly currentWork: CurrentWorkPort;
}

export interface TaskCommand {
  readonly intent: WorkIntent;
  readonly ref: TaskRef;
  readonly now: string;
  readonly sessionId?: string;
}

export type TaskCommandResult =
  | Readonly<{
      ok: false;
      kind: "plan";
      intent: WorkIntent;
      reason: PlanRejection;
    }>
  | Readonly<{
      ok: false;
      kind: "write";
      intent: WorkIntent;
      reason: Extract<TaskWriteResult, {ok: false}>["reason"];
    }>
  | Readonly<{
      ok: true;
      intent: WorkIntent;
      task: TaskRecord;
      currentWorkId: string | null;
      closedSession: WorkSession | null;
    }>;

function precondition(task: TaskRecord): TaskPrecondition {
  return Object.freeze({
    status: task.status,
    percentComplete: task.percentComplete,
    description: task.description,
  });
}

function verifyPatch(task: TaskRecord, patch: {
  readonly status?: TaskRecord["status"];
  readonly percentComplete?: number;
  readonly description?: string;
}): void {
  if ("status" in patch && task.status !== patch.status) {
    throw new Error(
      `VTODO read-back STATUS mismatch: expected ${String(patch.status)}, got ${String(task.status)}`,
    );
  }
  if (
    "percentComplete" in patch &&
    task.percentComplete !== patch.percentComplete
  ) {
    throw new Error(
      `VTODO read-back PERCENT-COMPLETE mismatch: expected ${patch.percentComplete}, got ${task.percentComplete}`,
    );
  }
  if ("description" in patch && task.description !== patch.description) {
    throw new Error("VTODO read-back DESCRIPTION mismatch.");
  }
}

function planFailure(plan: RejectedPlan): TaskCommandResult {
  return Object.freeze({
    ok: false,
    kind: "plan",
    intent: plan.intent,
    reason: plan.reason,
  });
}

/**
 * Imperative Task workflow shell.
 *
 * Durable VTODO state is committed and read back before currentWorkId changes.
 * A rejected optimistic write never changes currentWorkId. If the pointer write
 * itself fails after a verified VTODO commit, the error is deliberately
 * propagated without rolling the VTODO back; startup reconciliation can repair
 * the local pointer from the durable work-log.
 */
export async function executeTaskCommand(
  ports: TaskWorkflowPorts,
  command: TaskCommand,
): Promise<TaskCommandResult> {
  const currentWorkId = await ports.currentWork.getCurrentWorkId();
  const task = await ports.tasks.getTask(command.ref);

  const plan = planTaskAction({
    intent: command.intent,
    task,
    currentWorkId,
    now: command.now,
    sessionId: command.sessionId,
  });
  if (!plan.ok) return planFailure(plan);

  const write = await ports.tasks.updateTask(
    command.ref,
    plan.taskPatch,
    precondition(task),
  );
  if (!write.ok) {
    return Object.freeze({
      ok: false,
      kind: "write",
      intent: command.intent,
      reason: write.reason,
    });
  }

  verifyPatch(write.task, plan.taskPatch);

  const storedCurrentWorkId = await ports.currentWork.setCurrentWorkId(
    plan.nextCurrentWorkId,
  );
  if (storedCurrentWorkId !== plan.nextCurrentWorkId) {
    throw new Error(
      `currentWorkId read-back mismatch: expected ${String(plan.nextCurrentWorkId)}, got ${String(storedCurrentWorkId)}`,
    );
  }

  return Object.freeze({
    ok: true,
    intent: command.intent,
    task: write.task,
    currentWorkId: storedCurrentWorkId,
    closedSession: plan.closedSession,
  });
}
