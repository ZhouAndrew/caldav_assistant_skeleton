import {TaskSnapshot, WorkIntent} from "../domain";
import {openWorkSession, parseWorkDescription} from "../work-description";
import {MESSAGE_KEYS, MessageKey} from "../i18n";

export interface TaskPageView {
  readonly taskId: string;
  readonly title: string;
  readonly status: TaskSnapshot["status"];
  readonly percentComplete: number;
  readonly userDescription: string;
  readonly isCurrent: boolean;
  readonly elapsedMs: number;
  readonly actions: readonly WorkIntent[];
  readonly noticeKey: MessageKey | null;
  readonly errorKey: MessageKey | null;
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
      noticeKey: null,
      errorKey: MESSAGE_KEYS.taskWorkLogMalformed,
    });
  }

  const open = openWorkSession(parsed.value);
  const isCurrent = currentWorkId === task.taskId;
  const finished =
    task.status === "COMPLETED" ||
    task.status === "CANCELLED" ||
    task.percentComplete === 100;

  let actions: readonly WorkIntent[] = Object.freeze([]);
  let noticeKey: MessageKey | null = null;
  let errorKey: MessageKey | null = null;

  if (open && finished) {
    errorKey = MESSAGE_KEYS.taskFinishedOpenSession;
  } else if (isCurrent && open) {
    actions = Object.freeze(["stop", "complete", "cancel"]);
  } else if (isCurrent && !open) {
    errorKey = MESSAGE_KEYS.currentPointerStale;
  } else if (!isCurrent && open) {
    errorKey = MESSAGE_KEYS.openSessionNotCurrent;
  } else if (finished) {
    noticeKey = MESSAGE_KEYS.taskFinished;
  } else if (currentWorkId !== null) {
    noticeKey = MESSAGE_KEYS.anotherTaskActive;
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
    noticeKey,
    errorKey,
  });
}
