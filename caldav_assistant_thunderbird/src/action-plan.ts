import {
  AssistantRuntime,
  TaskSnapshot,
  TaskStatus,
  WorkAction,
  WorkTaskId,
} from "./domain";
import {TaskRestoreSnapshot} from "./restore-snapshot";

export type WorkHistoryEffect = "none" | "open" | "close";

export interface TaskChanges {
  readonly status?: TaskStatus;
  readonly paused?: boolean;
  readonly percentComplete?: number;
}

export type ActionPlanRejection =
  | "finished"
  | "current-work-exists"
  | "not-current"
  | "not-working"
  | "not-paused"
  | "restore-required";

export interface WorkActionPlan {
  readonly ok: true;
  readonly action: WorkAction;
  readonly taskChanges: Readonly<TaskChanges>;
  readonly nextCurrentWorkId: WorkTaskId | null;
  readonly historyEffect: WorkHistoryEffect;
}

export interface RejectedWorkActionPlan {
  readonly ok: false;
  readonly action: WorkAction;
  readonly reason: ActionPlanRejection;
}

export type PlannedWorkAction = WorkActionPlan | RejectedWorkActionPlan;

function reject(
  action: WorkAction,
  reason: ActionPlanRejection,
): RejectedWorkActionPlan {
  return Object.freeze({ok: false, action, reason});
}

function accept(
  action: WorkAction,
  taskChanges: TaskChanges,
  nextCurrentWorkId: WorkTaskId | null,
  historyEffect: WorkHistoryEffect,
): WorkActionPlan {
  return Object.freeze({
    ok: true,
    action,
    taskChanges: Object.freeze({...taskChanges}),
    nextCurrentWorkId,
    historyEffect,
  });
}

/**
 * Pure workflow decision.
 *
 * It contains no Thunderbird, storage, clock, WordPress or notification I/O.
 * The imperative shell executes the returned VTODO/currentWorkId/history effects
 * and verifies each authoritative write by read-back.
 */
export function planWorkAction(
  action: WorkAction,
  runtime: AssistantRuntime,
  task: TaskSnapshot,
  restoreSnapshot: TaskRestoreSnapshot | null = null,
): PlannedWorkAction {
  if (task.status === "COMPLETED" || task.status === "CANCELLED") {
    return reject(action, "finished");
  }

  const current = runtime.currentWorkId === task.workTaskId;

  switch (action) {
    case "start":
      if (runtime.currentWorkId !== null) {
        return reject(action, "current-work-exists");
      }
      return accept(
        action,
        {status: "IN-PROCESS", paused: false},
        task.workTaskId,
        "open",
      );

    case "pause":
      if (!current) return reject(action, "not-current");
      if (task.status !== "IN-PROCESS" || task.paused) {
        return reject(action, "not-working");
      }
      return accept(
        action,
        {status: "IN-PROCESS", paused: true},
        task.workTaskId,
        "close",
      );

    case "resume":
      if (!current) return reject(action, "not-current");
      if (task.status !== "IN-PROCESS" || !task.paused) {
        return reject(action, "not-paused");
      }
      return accept(
        action,
        {status: "IN-PROCESS", paused: false},
        task.workTaskId,
        "open",
      );

    case "complete":
      if (!current) return reject(action, "not-current");
      return accept(
        action,
        {status: "COMPLETED", paused: false, percentComplete: 100},
        null,
        "close",
      );

    case "cancel":
      if (!current) return reject(action, "not-current");
      return accept(
        action,
        {status: "CANCELLED", paused: false},
        null,
        "close",
      );

    case "switch-away":
      if (!current) return reject(action, "not-current");
      if (!restoreSnapshot) return reject(action, "restore-required");
      return accept(
        action,
        {
          status: restoreSnapshot.status,
          paused: restoreSnapshot.paused,
          percentComplete: restoreSnapshot.percentComplete,
        },
        null,
        "close",
      );
  }
}
