import {WorkIntent, WorkSession} from "./domain";
import {CurrentWorkStore, DiagnosticSink, TaskRepository} from "./ports";
import {planTaskAction} from "./workflow";

export interface TaskCommandDeps {
  readonly tasks: TaskRepository;
  readonly currentWork: CurrentWorkStore;
  readonly diagnostics?: DiagnosticSink;
}

export type TaskCommandFailureKind =
  | "task-read-failed"
  | "task-not-found"
  | "pointer-read-failed"
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
  readonly taskWriteAttempted: boolean;
  readonly taskVerified: boolean;
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

function errorText(error: unknown): string {
  return String(error instanceof Error ? error.message : error);
}

function failure(
  taskId: string,
  intent: WorkIntent,
  kind: TaskCommandFailureKind,
  message: string,
  taskWriteAttempted: boolean,
  taskVerified: boolean
): TaskCommandFailure {
  return Object.freeze({
    ok: false,
    taskId,
    intent,
    kind,
    message,
    taskWriteAttempted,
    taskVerified,
  });
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
  let task;
  try {
    task = await deps.tasks.get(taskId);
  } catch (error) {
    const message = errorText(error);
    await diag(deps.diagnostics, {
      kind: "task-read-failed",
      success: false,
      taskId,
      message,
    });
    return failure(taskId, intent, "task-read-failed", message, false, false);
  }

  if (!task) {
    await diag(deps.diagnostics, {
      kind: "task-not-found",
      success: false,
      taskId,
    });
    return failure(
      taskId,
      intent,
      "task-not-found",
      "Task not found.",
      false,
      false
    );
  }

  let currentWorkId: string | null;
  try {
    currentWorkId = await deps.currentWork.get();
  } catch (error) {
    const message = errorText(error);
    await diag(deps.diagnostics, {
      kind: "pointer-read-failed",
      success: false,
      taskId,
      message,
    });
    return failure(
      taskId,
      intent,
      "pointer-read-failed",
      message,
      false,
      false
    );
  }

  const plan = planTaskAction(intent, task, currentWorkId, nowIso, sessionId);
  if (!plan.ok) {
    await diag(deps.diagnostics, {
      kind: "transition-rejected",
      success: false,
      taskId,
      message: plan.reason,
    });
    return failure(
      taskId,
      intent,
      "transition-rejected",
      plan.reason,
      false,
      false
    );
  }

  try {
    await deps.tasks.update(taskId, plan.taskPatch, {
      description: task.description,
      status: task.status,
      percentComplete: task.percentComplete,
    });
  } catch (error) {
    const message = errorText(error);
    await diag(deps.diagnostics, {
      kind: "task-write-failed",
      success: false,
      taskId,
      message,
    });
    return failure(
      taskId,
      intent,
      "task-write-failed",
      message,
      true,
      false
    );
  }

  let stored;
  try {
    stored = await deps.tasks.get(taskId);
  } catch (error) {
    const message = errorText(error);
    await diag(deps.diagnostics, {
      kind: "readback-failed",
      success: false,
      taskId,
      message,
    });
    return failure(
      taskId,
      intent,
      "readback-failed",
      message,
      true,
      false
    );
  }

  if (!stored || !sameTaskState(plan.taskPatch, stored)) {
    await diag(deps.diagnostics, {
      kind: "readback-failed",
      success: false,
      taskId,
    });
    return failure(
      taskId,
      intent,
      "readback-failed",
      "Task read-back verification failed.",
      true,
      false
    );
  }

  try {
    await deps.currentWork.set(plan.nextCurrentWorkId);
  } catch (error) {
    const message = errorText(error);
    await diag(deps.diagnostics, {
      kind: "pointer-write-failed",
      success: false,
      taskId,
      message,
    });
    return failure(
      taskId,
      intent,
      "pointer-write-failed",
      message,
      true,
      true
    );
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
