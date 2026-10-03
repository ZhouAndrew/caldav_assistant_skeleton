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
 * Pure workflow decision for the reduced lifecycle:
 * Start / Stop / Complete / Cancel.
 *
 * Stop restores the pre-Start status/progress from immutable history while
 * normalizing any old paused marker off. No new Pause/Resume state is created.
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

    case "stop":
      if (!current) return reject(action, "not-current");
      if (!restoreSnapshot) return reject(action, "restore-required");
      return accept(
        action,
        {
          status: restoreSnapshot.status,
          paused: false,
          percentComplete: restoreSnapshot.percentComplete,
        },
        null,
        "close",
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
  }
}
