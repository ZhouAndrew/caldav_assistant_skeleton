import {
  AcceptedTransition,
  PlannedTransition,
  RejectionReason,
  TaskSnapshot,
  WorkIntent,
  WorkSession,
} from "./domain";
import {
  closeOpenSession,
  openSession,
  openWorkSession,
  parseWorkDescription,
  serializeWorkDescription,
} from "./work-description";

function reject(intent: WorkIntent, reason: RejectionReason): PlannedTransition {
  return Object.freeze({ok: false, intent, reason});
}

function accepted(
  intent: WorkIntent,
  task: TaskSnapshot,
  description: string,
  status: TaskSnapshot["status"],
  percentComplete: number,
  nextCurrentWorkId: string | null,
  closedSession: WorkSession | null
): AcceptedTransition {
  return Object.freeze({
    ok: true,
    intent,
    taskPatch: Object.freeze({
      description,
      status,
      percentComplete,
    }),
    nextCurrentWorkId,
    closedSession,
  });
}

export function planTaskAction(
  intent: WorkIntent,
  task: TaskSnapshot,
  currentWorkId: string | null,
  nowIso: string,
  sessionId: string
): PlannedTransition {
  const parsed = parseWorkDescription(task.description);
  if (!parsed.ok) return reject(intent, "description-invalid");

  const open = openWorkSession(parsed.value);
  const isCurrent = currentWorkId === task.taskId;
  const finished =
    task.status === "COMPLETED" ||
    task.status === "CANCELLED" ||
    task.percentComplete === 100;

  if (intent === "start") {
    if (finished) return reject(intent, "finished");
    if (currentWorkId !== null) return reject(intent, "current-work-exists");
    if (open) return reject(intent, "open-session-exists");

    const opened = openSession(parsed.value, Object.freeze({
      id: sessionId,
      start: nowIso,
      end: null,
      result: null,
      before: Object.freeze({
        status: task.status,
        percentComplete: task.percentComplete,
      }),
    }));
    if (!opened) return reject(intent, "open-session-exists");

    return accepted(
      intent,
      task,
      serializeWorkDescription(opened),
      "IN-PROCESS",
      task.percentComplete,
      task.taskId,
      null
    );
  }

  if (!isCurrent) return reject(intent, "not-current");
  if (!open) return reject(intent, "open-session-missing");

  const closed = closeOpenSession(parsed.value, nowIso, intent);
  if (!closed) return reject(intent, "description-invalid");

  if (intent === "stop") {
    return accepted(
      intent,
      task,
      serializeWorkDescription(closed.value),
      open.before.status,
      open.before.percentComplete,
      null,
      closed.closed
    );
  }

  if (intent === "complete") {
    return accepted(
      intent,
      task,
      serializeWorkDescription(closed.value),
      "COMPLETED",
      100,
      null,
      closed.closed
    );
  }

  return accepted(
    intent,
    task,
    serializeWorkDescription(closed.value),
    "CANCELLED",
    task.percentComplete,
    null,
    closed.closed
  );
}
