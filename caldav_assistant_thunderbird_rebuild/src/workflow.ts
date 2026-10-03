import {
  AcceptedPlan,
  TaskActionPlan,
  TaskSnapshot,
  WorkIntent,
  WorkResult,
  WorkSession,
  isFinished,
  normalizePercent,
  taskId,
} from "./domain";
import {
  closeSession,
  openSession,
  openSessions,
  parseWorkDescription,
  serializeWorkDescription,
} from "./work-description";

function reject(intent: WorkIntent, reason: TaskActionPlan extends never ? never : any): TaskActionPlan {
  return Object.freeze({ok: false, intent, reason});
}

function accept(
  intent: WorkIntent,
  taskPatch: AcceptedPlan["taskPatch"],
  nextCurrentWorkId: string | null,
  closedSession: WorkSession | null,
): AcceptedPlan {
  return Object.freeze({
    ok: true,
    intent,
    taskPatch: Object.freeze({...taskPatch}),
    nextCurrentWorkId,
    closedSession,
  });
}

function closeResult(intent: Exclude<WorkIntent, "start">): WorkResult {
  return intent;
}

export function planTaskAction(args: {
  readonly intent: WorkIntent;
  readonly task: TaskSnapshot;
  readonly currentWorkId: string | null;
  readonly now: string;
  readonly sessionId?: string;
}): TaskActionPlan {
  const {intent, task, currentWorkId, now} = args;
  if (!Number.isFinite(Date.parse(now))) {
    return reject(intent, "description-invalid");
  }

  const parsed = parseWorkDescription(task.description);
  if (!parsed.ok) return reject(intent, "description-invalid");

  const id = taskId(task);
  const open = openSessions(parsed.value);

  if (intent === "start") {
    if (isFinished(task)) return reject(intent, "finished");
    if (currentWorkId !== null) return reject(intent, "current-work-exists");
    if (open.length > 0) return reject(intent, "open-session-exists");

    const sessionId = String(args.sessionId || "");
    if (!sessionId) return reject(intent, "description-invalid");

    const session: WorkSession = Object.freeze({
      id: sessionId,
      start: now,
      end: null,
      result: null,
      before: Object.freeze({
        status: task.status,
        percentComplete: normalizePercent(task.percentComplete),
      }),
    });

    const next = openSession(parsed.value, session);
    if (!next) return reject(intent, "open-session-exists");

    return accept(
      intent,
      {
        status: "IN-PROCESS",
        description: serializeWorkDescription(next),
      },
      id,
      null,
    );
  }

  if (currentWorkId !== id) return reject(intent, "not-current");
  if (open.length === 0) return reject(intent, "open-session-missing");
  if (open.length !== 1) return reject(intent, "open-session-ambiguous");

  const active = open[0];
  const result = closeResult(intent);
  const next = closeSession(parsed.value, active.id, now, result);
  if (!next) return reject(intent, "description-invalid");
  const description = serializeWorkDescription(next);

  if (intent === "stop") {
    return accept(
      intent,
      {
        status: active.before.status,
        percentComplete: active.before.percentComplete,
        description,
      },
      null,
      Object.freeze({...active, end: now, result}),
    );
  }

  if (intent === "complete") {
    return accept(
      intent,
      {status: "COMPLETED", percentComplete: 100, description},
      null,
      Object.freeze({...active, end: now, result}),
    );
  }

  return accept(
    intent,
    {status: "CANCELLED", description},
    null,
    Object.freeze({...active, end: now, result}),
  );
}

export function deriveTaskPage(args: {
  readonly task: TaskSnapshot;
  readonly currentWorkId: string | null;
}): Readonly<{
  taskId: string;
  isCurrent: boolean;
  anotherTaskIsCurrent: boolean;
  actions: readonly WorkIntent[];
}> {
  const id = taskId(args.task);
  const isCurrent = args.currentWorkId === id;
  let actions: readonly WorkIntent[] = Object.freeze([]);

  if (!isFinished(args.task)) {
    if (isCurrent) {
      actions = Object.freeze(["stop", "complete", "cancel"] as const);
    } else if (args.currentWorkId === null) {
      actions = Object.freeze(["start"] as const);
    }
  }

  return Object.freeze({
    taskId: id,
    isCurrent,
    anotherTaskIsCurrent:
      args.currentWorkId !== null && args.currentWorkId !== id,
    actions,
  });
}
