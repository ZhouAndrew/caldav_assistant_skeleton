import {
  CurrentWorkStore,
  DiagnosticSink,
  TaskCatalog,
  TaskRepository,
} from "./ports";
import {
  RecoveryDecision,
  decideRecoveryForPointer,
  decideRecoveryFromScan,
} from "./recovery";

export interface RecoveryDeps {
  readonly tasks: TaskRepository & TaskCatalog;
  readonly currentWork: CurrentWorkStore;
  readonly diagnostics?: DiagnosticSink;
}

export interface RecoveryResult {
  readonly ok: boolean;
  readonly changed: boolean;
  readonly currentWorkId: string | null;
  readonly decision: RecoveryDecision;
  readonly message: string;
}

async function diag(
  sink: DiagnosticSink | undefined,
  success: boolean,
  message: string
): Promise<void> {
  if (!sink) return;
  try {
    await sink.record({kind: "recovery", success, message});
  } catch {
    // Recovery must not depend on diagnostics.
  }
}

export async function recoverCurrentWork(
  deps: RecoveryDeps
): Promise<RecoveryResult> {
  let current: string | null;
  try {
    current = await deps.currentWork.get();
  } catch (error) {
    const message = String(error instanceof Error ? error.message : error);
    const decision: RecoveryDecision = {
      kind: "conflict",
      reason: "current-pointer-read-failed",
    };
    await diag(deps.diagnostics, false, message);
    return {ok: false, changed: false, currentWorkId: null, decision, message};
  }

  let decision: RecoveryDecision;
  if (current !== null) {
    try {
      const task = await deps.tasks.get(current);
      decision = decideRecoveryForPointer(current, task);
    } catch (error) {
      const message = String(error instanceof Error ? error.message : error);
      decision = {kind: "conflict", reason: "current-task-read-failed"};
      await diag(deps.diagnostics, false, message);
      return {
        ok: false,
        changed: false,
        currentWorkId: current,
        decision,
        message,
      };
    }
  } else {
    try {
      decision = decideRecoveryFromScan(await deps.tasks.scanStored());
    } catch (error) {
      const message = String(error instanceof Error ? error.message : error);
      decision = {kind: "conflict", reason: "task-scan-failed"};
      await diag(deps.diagnostics, false, message);
      return {
        ok: false,
        changed: false,
        currentWorkId: null,
        decision,
        message,
      };
    }
  }

  if (decision.kind === "conflict") {
    await diag(deps.diagnostics, false, decision.reason);
    return {
      ok: false,
      changed: false,
      currentWorkId: current,
      decision,
      message: decision.reason,
    };
  }

  const target =
    decision.kind === "set"
      ? decision.currentWorkId
      : decision.kind === "clear"
        ? null
        : decision.currentWorkId;

  if (target === current) {
    await diag(deps.diagnostics, true, "no-change");
    return {
      ok: true,
      changed: false,
      currentWorkId: current,
      decision,
      message: "no-change",
    };
  }

  try {
    await deps.currentWork.set(target);
  } catch (error) {
    const message = String(error instanceof Error ? error.message : error);
    const failed: RecoveryDecision = {
      kind: "conflict",
      reason: "current-pointer-write-failed",
    };
    await diag(deps.diagnostics, false, message);
    return {
      ok: false,
      changed: false,
      currentWorkId: current,
      decision: failed,
      message,
    };
  }

  await diag(deps.diagnostics, true, decision.kind);
  return {
    ok: true,
    changed: true,
    currentWorkId: target,
    decision,
    message: decision.kind,
  };
}
