import {
  AssistantRuntime,
  DerivedWorkState,
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

/**
 * Derive UI/workflow state. "working" and "paused" are not persisted Assistant
 * runtime states: they come from currentWorkId + the current VTODO facts.
 */
export function deriveWorkState(
  runtime: AssistantRuntime,
  task: TaskSnapshot | null,
): DerivedWorkState {
  if (!runtime.currentWorkId || !task) return "idle";
  if (!isCurrentTask(runtime, task) || isFinished(task)) return "idle";
  return task.paused ? "paused" : "working";
}

export function actionAllowed(
  action: WorkAction,
  runtime: AssistantRuntime,
  task: TaskSnapshot,
): boolean {
  const current = isCurrentTask(runtime, task);

  if (isFinished(task)) return false;

  switch (action) {
    case "start":
      return runtime.currentWorkId === null;
    case "pause":
      return current && !task.paused;
    case "resume":
      return current && task.paused;
    case "complete":
    case "cancel":
    case "switch-away":
      return current;
  }
}

/**
 * Pure runtime transition. It deliberately changes only currentWorkId.
 * VTODO status/paused/progress changes are separate CalDAV effects.
 */
export function nextRuntime(
  action: WorkAction,
  runtime: AssistantRuntime,
  task: TaskSnapshot,
): AssistantRuntime {
  if (!actionAllowed(action, runtime, task)) {
    return runtime;
  }

  let currentWorkId: WorkTaskId | null = runtime.currentWorkId;
  switch (action) {
    case "start":
    case "resume":
    case "pause":
      currentWorkId = task.workTaskId;
      break;
    case "complete":
    case "cancel":
    case "switch-away":
      currentWorkId = null;
      break;
  }

  if (currentWorkId === runtime.currentWorkId) return runtime;
  return Object.freeze({currentWorkId});
}
