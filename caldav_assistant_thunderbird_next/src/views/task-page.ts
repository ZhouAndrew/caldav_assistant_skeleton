import {TaskSnapshot, WorkIntent} from "../../domain";
import {openWorkSession, parseWorkDescription} from "../../work-description";

export interface TaskPageView {
  readonly taskId: string;
  readonly title: string;
  readonly status: TaskSnapshot["status"];
  readonly percentComplete: number;
  readonly userDescription: string;
  readonly isCurrent: boolean;
  readonly elapsedMs: number;
  readonly actions: readonly WorkIntent[];
  readonly notice: string | null;
  readonly error: string | null;
}

function elapsed(start: string, now: string): number {
  const a = Date.parse(start);
  const b = Date.parse(now);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return 0;
  return Math.max(0, b - a);
}

export function deriveTaskPageView(
  task: TaskSnapshot,
  currentWorkId: string | null,
  nowIso: string
): TaskPageView {
  const parsed = parseWorkDescription(task.description);
  if (!parsed.ok) {
    return Object.freeze({
      taskId: task.taskId,
      title: task.title,
      status: task.status,
      percentComplete: task.percentComplete,
      userDescription: task.description,
      isCurrent: currentWorkId === task.taskId,
      elapsedMs: 0,
      actions: Object.freeze([]),
      notice: null,
      error: "Task work log is malformed. No workflow action is allowed.",
    });
  }

  const open = openWorkSession(parsed.value);
  const isCurrent = currentWorkId === task.taskId;
  const finished =
    task.status === "COMPLETED" ||
    task.status === "CANCELLED" ||
    task.percentComplete === 100;

  let actions: readonly WorkIntent[] = Object.freeze([]);
  let notice: string | null = null;
  let error: string | null = null;

  if (open && finished) {
    error = "Finished Task still has an open work session.";
  } else if (isCurrent && open) {
    actions = Object.freeze(["stop", "complete", "cancel"]);
  } else if (isCurrent && !open) {
    error = "Current-work pointer is stale. Recovery is required.";
  } else if (!isCurrent && open) {
    error = "Task has an open work session but is not the current Task. Recovery is required.";
  } else if (finished) {
    notice = "Task is finished.";
  } else if (currentWorkId !== null) {
    notice = "Another Task is currently active.";
  } else {
    actions = Object.freeze(["start"]);
  }

  return Object.freeze({
    taskId: task.taskId,
    title: task.title,
    status: task.status,
    percentComplete: task.percentComplete,
    userDescription: parsed.value.userText,
    isCurrent,
    elapsedMs: open ? elapsed(open.start, nowIso) : 0,
    actions,
    notice,
    error,
  });
}
