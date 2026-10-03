import {
  AcceptedPlan,
  RejectedPlan,
  TaskSnapshot,
  WorkIntent,
  WorkPlan,
  WorkSession,
} from "./domain";
import {makeTaskId} from "./task-id";
import {
  closeWorkSession,
  getOpenSession,
  openWorkSession,
  parseWorkDescription,
  serializeWorkDescription,
} from "./work-description";

function reject(
  intent: WorkIntent,
  reason: RejectedPlan["reason"]
): RejectedPlan {
  return Object.freeze({ok: false, intent, reason});
}

function accept(
  intent: WorkIntent,
  taskPatch: AcceptedPlan["taskPatch"],
  nextCurrentWorkId: string | null,
  closedSession: WorkSession | null
): AcceptedPlan {
  return Object.freeze({
    ok: true,
    intent,
    taskPatch: Object.freeze({...taskPatch}),
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
): WorkPlan {
  if (task.status === "COMPLETED" || task.status === "CANCELLED") {
    return reject(intent, "finished");
  }

  const parsed = parseWorkDescription(task.description);
  if (!parsed.ok) return reject(intent, "description-corrupt");

  const taskWorkId = makeTaskId(task);
  const isCurrent = currentWorkId === taskWorkId;
  const open = getOpenSession(parsed);

  if (intent === "start") {
    if (currentWorkId !== null) return reject(intent, "current-work-exists");
    if (open) return reject(intent, "open-session-exists");

    const session: WorkSession = Object.freeze({
      id: sessionId,
      start: nowIso,
      end: null,
      result: null,
      before: Object.freeze({
        status: task.status,
        percentComplete: task.percentComplete,
      }),
    });
    const opened = openWorkSession(parsed, session);
    if (!opened) return reject(intent, "description-corrupt");

    return accept(
      intent,
      {
        description: serializeWorkDescription(opened),
        status: "IN-PROCESS",
      },
      taskWorkId,
      null
    );
  }

  if (!isCurrent) return reject(intent, "not-current");
  if (!open) return reject(intent, "open-session-missing");

  const closed = closeWorkSession(parsed, open.id, nowIso, intent);
  if (!closed) return reject(intent, "description-corrupt");

  const closedSession = getOpenSession(closed) === null
    ? closed.workLog.sessions.find(item => item.id === open.id) ?? null
    : null;
  if (!closedSession) return reject(intent, "description-corrupt");

  if (intent === "stop") {
    return accept(
      intent,
      {
        description: serializeWorkDescription(closed),
        status: open.before.status,
        percentComplete: open.before.percentComplete,
      },
      null,
      closedSession
    );
  }

  if (intent === "complete") {
    return accept(
      intent,
      {
        description: serializeWorkDescription(closed),
        status: "COMPLETED",
        percentComplete: 100,
      },
      null,
      closedSession
    );
  }

  return accept(
    intent,
    {
      description: serializeWorkDescription(closed),
      status: "CANCELLED",
    },
    null,
    closedSession
  );
}
