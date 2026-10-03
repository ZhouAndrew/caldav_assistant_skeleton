import {
  AssistantRuntime,
  TaskSnapshot,
  WorkAction,
  WorkTaskId,
} from "./domain";

export function isFinished(task: TaskSnapshot): boolean {
  return task.status === "COMPLETED" || task.status === "CANCELLED";
}

export function isCurrentTask(
  runtime: AssistantRuntime,
  task: TaskSnapshot,
): boolean {
  return runtime.currentWorkId === task.workTaskId;
}

export function actionAllowed(
  action: WorkAction,
  runtime: AssistantRuntime,
  task: TaskSnapshot,
): boolean {
  if (isFinished(task)) return false;

  const current = isCurrentTask(runtime, task);
  switch (action) {
    case "start":
      return runtime.currentWorkId === null;
    case "stop":
    case "complete":
    case "cancel":
      return current;
  }
}

/**
 * Pure Assistant-pointer transition. It changes only currentWorkId.
 * VTODO changes are separate Thunderbird/CalDAV effects.
 */
export function nextRuntime(
  action: WorkAction,
  runtime: AssistantRuntime,
  task: TaskSnapshot,
): AssistantRuntime {
  if (!actionAllowed(action, runtime, task)) return runtime;

  const currentWorkId: WorkTaskId | null =
    action === "start" ? task.workTaskId : null;

  if (currentWorkId === runtime.currentWorkId) return runtime;
  return Object.freeze({currentWorkId});
}
