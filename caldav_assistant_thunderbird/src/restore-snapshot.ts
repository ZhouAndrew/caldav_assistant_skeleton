import {
  TaskSnapshot,
  TaskStatus,
  WorkTaskId,
} from "./domain";

export interface TaskRestoreSnapshot {
  readonly status: TaskStatus;
  readonly paused: boolean;
  readonly percentComplete: number;
}

export interface StartReceiptTask {
  readonly workTaskId: WorkTaskId;
  readonly beforeStatus: TaskStatus | null;
  readonly beforePaused: boolean;
  readonly beforePercentComplete: number;
}

function normalizePercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(99, Math.trunc(value)));
}

/**
 * Recover the exact pre-Start Task state from immutable workflow history.
 *
 * This is intentionally pure. The Activity/Audit lookup stays in the effect
 * boundary; the functional core only validates identity and returns a snapshot.
 */
export function restoreSnapshotFromStartReceipt(
  task: TaskSnapshot,
  receiptTask: StartReceiptTask | null,
): TaskRestoreSnapshot | null {
  if (!receiptTask || receiptTask.workTaskId !== task.workTaskId) return null;

  const status = receiptTask.beforeStatus ?? "NEEDS-ACTION";
  if (status === "COMPLETED" || status === "CANCELLED") return null;

  return Object.freeze({
    status,
    paused: Boolean(receiptTask.beforePaused),
    percentComplete: normalizePercent(receiptTask.beforePercentComplete),
  });
}

/**
 * Conservative recovery when immutable pre-Start history is unavailable.
 *
 * Keep existing progress, release Assistant pause state, and return to an
 * incomplete standard VTODO state rather than inventing completion/cancellation.
 */
export function fallbackRestoreSnapshot(
  task: TaskSnapshot,
): TaskRestoreSnapshot {
  return Object.freeze({
    status: "NEEDS-ACTION",
    paused: false,
    percentComplete: normalizePercent(task.percentComplete),
  });
}
