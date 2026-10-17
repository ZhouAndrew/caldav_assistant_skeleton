import {TaskPatch, TaskSnapshot} from "../src/domain";
import {CurrentWorkStore, TaskCatalog, TaskRepository, TaskScanResult} from "../src/ports";
import {recoverCurrentWork} from "../src/recovery-service";
import {decideRecoveryFromScan, decideRecoveryForPointer} from "../src/recovery";
import {encodeTaskId} from "../src/task-id";
import {planTaskAction} from "../src/workflow";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function plainTask(uid: string): TaskSnapshot {
  const identity = {calendarId: "tasks", uid, recurrenceId: ""};
  return Object.freeze({
    ...identity,
    taskId: encodeTaskId(identity),
    title: uid,
    description: "用户说明",
    status: "NEEDS-ACTION",
    percentComplete: 20,
  });
}

function openTask(uid: string): TaskSnapshot {
  const base = plainTask(uid);
  const plan = planTaskAction(
    "start",
    base,
    null,
    "2026-10-03T19:00:00+08:00",
    "session-" + uid
  );
  assert(plan.ok, "test fixture Start failed");
  return Object.freeze({
    ...base,
    description: plan.taskPatch.description,
    status: plan.taskPatch.status,
    percentComplete: plan.taskPatch.percentComplete,
  });
}

function closedTask(uid: string): TaskSnapshot {
  const opened = openTask(uid);
  const plan = planTaskAction(
    "stop",
    opened,
    opened.taskId,
    "2026-10-03T19:30:00+08:00",
    "unused"
  );
  assert(plan.ok, "test fixture Stop failed");
  return Object.freeze({
    ...opened,
    description: plan.taskPatch.description,
    status: plan.taskPatch.status,
    percentComplete: plan.taskPatch.percentComplete,
  });
}

class RecoveryRepo implements TaskRepository, TaskCatalog {
  constructor(
    readonly items: TaskSnapshot[],
    readonly scanComplete = true,
    readonly scanFailures: {calendarId: string; message: string}[] = []
  ) {}

  async get(taskId: string): Promise<TaskSnapshot | null> {
    return this.items.find(task => task.taskId === taskId) ?? null;
  }

  async update(_taskId: string, _patch: TaskPatch): Promise<void> {
    throw new Error("recovery must never update VTODO");
  }

  async scanStored(): Promise<TaskScanResult> {
    return {
      tasks: this.items,
      complete: this.scanComplete,
      failures: this.scanFailures,
    };
  }
}

class Pointer implements CurrentWorkStore {
  writes: Array<string | null> = [];
  constructor(public value: string | null) {}

  async get(): Promise<string | null> {
    return this.value;
  }

  async set(value: string | null): Promise<void> {
    this.writes.push(value);
    this.value = value;
  }
}

async function main(): Promise<void> {
  const active = openTask("active");

  const keep = decideRecoveryForPointer(active.taskId, active);
  assert(
    keep.kind === "keep" && keep.currentWorkId === active.taskId,
    "valid pointer/open session was not kept"
  );

  const stopped = closedTask("stopped");
  const clear = decideRecoveryForPointer(stopped.taskId, stopped);
  assert(clear.kind === "clear", "stale pointer was not identified");

  const unique = decideRecoveryFromScan({
    tasks: [plainTask("a"), active],
    complete: true,
    failures: [],
  });
  assert(
    unique.kind === "set" && unique.currentWorkId === active.taskId,
    "unique open session was not recoverable"
  );

  const partial = decideRecoveryFromScan({
    tasks: [active],
    complete: false,
    failures: [{calendarId: "broken", message: "offline"}],
  });
  assert(
    partial.kind === "conflict" && partial.reason === "task-scan-incomplete",
    "partial scan guessed a pointer"
  );

  const another = openTask("another");
  const multiple = decideRecoveryFromScan({
    tasks: [active, another],
    complete: true,
    failures: [],
  });
  assert(
    multiple.kind === "conflict" && multiple.reason === "multiple-open-sessions",
    "multiple open sessions were guessed"
  );

  const malformed = Object.freeze({
    ...plainTask("bad"),
    description:
      "user\n\n[CALDAV-ASSISTANT-WORKLOG v1]\n{bad}\n[/CALDAV-ASSISTANT-WORKLOG]",
  });
  const malformedDecision = decideRecoveryFromScan({
    tasks: [malformed],
    complete: true,
    failures: [],
  });
  assert(
    malformedDecision.kind === "conflict" &&
      malformedDecision.reason.startsWith("malformed-description:"),
    "malformed Description did not stop recovery"
  );

  const terminalOpen = Object.freeze({
    ...active,
    status: "COMPLETED" as const,
    percentComplete: 100,
  });
  const terminalDecision = decideRecoveryFromScan({
    tasks: [terminalOpen],
    complete: true,
    failures: [],
  });
  assert(
    terminalDecision.kind === "conflict" &&
      terminalDecision.reason.startsWith("terminal-task-has-open-session:"),
    "terminal Task with open session was silently accepted"
  );

  // Crash window: Start VTODO committed/read-back, pointer write did not happen.
  const startPointer = new Pointer(null);
  const startRecovery = await recoverCurrentWork({
    tasks: new RecoveryRepo([plainTask("other"), active]),
    currentWork: startPointer,
  });
  assert(startRecovery.ok && startRecovery.changed, "Start crash was not recovered");
  assert(startPointer.value === active.taskId, "Start crash restored wrong pointer");
  assert(startPointer.writes.length === 1, "Start recovery wrote pointer unexpectedly many times");

  // Crash window: Stop VTODO committed/read-back, pointer clear did not happen.
  const stopPointer = new Pointer(stopped.taskId);
  const stopRecovery = await recoverCurrentWork({
    tasks: new RecoveryRepo([stopped]),
    currentWork: stopPointer,
  });
  assert(stopRecovery.ok && stopRecovery.changed, "Stop crash was not recovered");
  assert(stopPointer.value === null, "Stop crash did not clear stale pointer");

  const partialPointer = new Pointer(null);
  const partialRecovery = await recoverCurrentWork({
    tasks: new RecoveryRepo(
      [active],
      false,
      [{calendarId: "broken", message: "provider unavailable"}]
    ),
    currentWork: partialPointer,
  });
  assert(!partialRecovery.ok, "partial scan recovery reported success");
  assert(partialPointer.writes.length === 0, "partial scan mutated pointer");

  const multiPointer = new Pointer(null);
  const multiRecovery = await recoverCurrentWork({
    tasks: new RecoveryRepo([active, another]),
    currentWork: multiPointer,
  });
  assert(!multiRecovery.ok, "multiple session recovery reported success");
  assert(multiPointer.writes.length === 0, "multiple session recovery mutated pointer");

  console.log("clean-room recovery: PASS");
}

main().catch(error => {
  console.error(error);
  throw error;
});
