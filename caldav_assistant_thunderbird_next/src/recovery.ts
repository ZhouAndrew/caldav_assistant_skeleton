import {TaskSnapshot} from "./domain";
import {TaskScanResult} from "./ports";
import {openWorkSession, parseWorkDescription} from "./work-description";

export type RecoveryDecision =
  | {readonly kind: "keep"; readonly currentWorkId: string | null}
  | {readonly kind: "set"; readonly currentWorkId: string}
  | {readonly kind: "clear"}
  | {readonly kind: "conflict"; readonly reason: string};

function taskOpenState(task: TaskSnapshot):
  | {readonly ok: true; readonly open: boolean}
  | {readonly ok: false; readonly reason: string} {
  const parsed = parseWorkDescription(task.description);
  if (!parsed.ok) {
    return {ok: false, reason: `malformed-description:${task.taskId}`};
  }

  const open = openWorkSession(parsed.value);
  if (
    open &&
    (task.status === "COMPLETED" ||
      task.status === "CANCELLED" ||
      task.percentComplete === 100)
  ) {
    return {ok: false, reason: `terminal-task-has-open-session:${task.taskId}`};
  }
  return {ok: true, open: Boolean(open)};
}

/**
 * Pure recovery decision.
 *
 * This function does not read audit/history and never guesses across partial data.
 */
export function decideRecoveryForPointer(
  currentWorkId: string,
  task: TaskSnapshot | null
): RecoveryDecision {
  if (!task) {
    return {kind: "conflict", reason: "current-task-not-readable"};
  }
  if (task.taskId !== currentWorkId) {
    return {kind: "conflict", reason: "current-task-identity-mismatch"};
  }

  const state = taskOpenState(task);
  if (!state.ok) return {kind: "conflict", reason: state.reason};
  if (state.open) return {kind: "keep", currentWorkId};
  return {kind: "clear"};
}

export function decideRecoveryFromScan(
  scan: TaskScanResult
): RecoveryDecision {
  if (!scan.complete) {
    return {kind: "conflict", reason: "task-scan-incomplete"};
  }

  const openTaskIds: string[] = [];
  for (const task of scan.tasks) {
    const state = taskOpenState(task);
    if (!state.ok) {
      return {kind: "conflict", reason: state.reason};
    }
    if (state.open) openTaskIds.push(task.taskId);
  }

  const unique = [...new Set(openTaskIds)];
  if (unique.length === 0) return {kind: "keep", currentWorkId: null};
  if (unique.length === 1) return {kind: "set", currentWorkId: unique[0]!};
  return {kind: "conflict", reason: "multiple-open-sessions"};
}
