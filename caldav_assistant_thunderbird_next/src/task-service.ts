import {WorkIntent, WorkSession} from "./domain";
import {CurrentWorkStore, DiagnosticSink, TaskRepository} from "./ports";
import {planTaskAction} from "./workflow";

export interface TaskCommandDeps {
  readonly tasks: TaskRepository;
  readonly currentWork: CurrentWorkStore;
  readonly diagnostics?: DiagnosticSink;
}

export type TaskCommandFailureKind =
  | "task-not-found"
  | "transition-rejected"
  | "task-write-failed"
  | "readback-failed"
  | "pointer-write-failed";

export interface TaskCommandSuccess {
  readonly ok: true;
  readonly taskId: string;
  readonly intent: WorkIntent;
  readonly currentWorkId: string | null;
  readonly closedSession: WorkSession | null;
}

export interface TaskCommandFailure {
  readonly ok: false;
  readonly taskId: string;
  readonly intent: WorkIntent;
  readonly kind: TaskCommandFailureKind;
  readonly message: string;
  readonly taskCommitted: boolean;
}

export type TaskCommandResult = TaskCommandSuccess | TaskCommandFailure;

async function diag(
  sink: DiagnosticSink | undefined,
  entry: Parameters<DiagnosticSink["record"]>[0]
): Promise<void> {
  if (!sink) return;
  try {
    await sink.record(entry);
  } catch {
    // Diagnostics are observational and must never change command semantics.
  }
}

function sameTaskState(
  expected: {
    readonly description: string;
    readonly status: string;
    readonly percentComplete: number;
  },
  actual: {
    readonly description: string;
    readonly status: string;
    readonly percentComplete: number;
  }
): boolean {
  return expected.description === actual.description &&
    expected.status === actual.status &&
    expected.percentComplete === actual.percentComplete;
}

export async function runTaskCommand(
  deps: TaskCommandDeps,
  intent: WorkIntent,
  taskId: string,
  nowIso: string,
  sessionId: string
): Promise<TaskCommandResult> {
  const task = await deps.tasks.get(taskId);
  if (!task) {
    await diag(deps.diagnostics, {
      kind: "task-not-found",
      success: false,
      taskId,
    });
    return Object.freeze({
      ok: false,
      taskId,
      intent,
      kind: "task-not-found",
      message: "Task not found.",
      taskCommitted: false,
    });
  }

  const currentWorkId = await deps.currentWork.get();
  const plan = planTaskAction(intent, task, currentWorkId, nowIso, sessionId);
  if (!plan.ok) {
    await diag(deps.diagnostics, {
      kind: "transition-rejected",
      success: false,
      taskId,
      message: plan.reason,
    });
    return Object.freeze({
      ok: false,
      taskId,
      intent,
      kind: "transition-rejected",
      message: plan.reason,
      taskCommitted: false,
    });
  }

  try {
    await deps.tasks.update(taskId, plan.taskPatch);
  } catch (error) {
    const message = String(error instanceof Error ? error.message : error);
    await diag(deps.diagnostics, {
      kind: "task-write-failed",
      success: false,
      taskId,
      message,
    });
    return Object.freeze({
      ok: false,
      taskId,
      intent,
      kind: "task-write-failed",
      message,
      taskCommitted: false,
    });
  }

  const stored = await deps.tasks.get(taskId);
  if (!stored || !sameTaskState(plan.taskPatch, stored)) {
    await diag(deps.diagnostics, {
      kind: "readback-failed",
      success: false,
      taskId,
    });
    return Object.freeze({
      ok: false,
      taskId,
      intent,
      kind: "readback-failed",
      message: "Task read-back verification failed.",
      taskCommitted: false,
    });
  }

  try {
    await deps.currentWork.set(plan.nextCurrentWorkId);
  } catch (error) {
    const message = String(error instanceof Error ? error.message : error);
    await diag(deps.diagnostics, {
      kind: "pointer-write-failed",
      success: false,
      taskId,
      message,
    });
    return Object.freeze({
      ok: false,
      taskId,
      intent,
      kind: "pointer-write-failed",
      message,
      taskCommitted: true,
    });
  }

  await diag(deps.diagnostics, {
    kind: intent,
    success: true,
    taskId,
  });
  return Object.freeze({
    ok: true,
    taskId,
    intent,
    currentWorkId: plan.nextCurrentWorkId,
    closedSession: plan.closedSession,
  });
}
