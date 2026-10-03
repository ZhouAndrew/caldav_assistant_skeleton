import {TaskPatch, TaskRef, TaskSnapshot} from "../src/domain";
import {makeTaskId} from "../src/task-id";
import {
  CurrentWorkPort,
  ThunderbirdTaskPort,
  executeTaskCommand,
  reconcileCurrentWork,
} from "../src/workflow-service";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function cloneTask(task: TaskSnapshot): TaskSnapshot {
  return Object.freeze({...task});
}

class FakeTasks implements ThunderbirdTaskPort {
  task: TaskSnapshot;
  failWrite = false;
  failRead = false;
  failReadAfterWrite = false;
  writeAttempted = false;
  mismatch = false;
  calls: string[] = [];
  trace: string[];

  constructor(task: TaskSnapshot, trace: string[] = []) {
    this.task = task;
    this.trace = trace;
  }

  async getTask(_ref: TaskRef): Promise<TaskSnapshot> {
    this.calls.push("task.get");
    this.trace.push("task.get");
    if (
      this.failRead ||
      (this.failReadAfterWrite && this.writeAttempted)
    ) {
      throw new Error("read failed");
    }
    return cloneTask(this.task);
  }

  async updateTask(_ref: TaskRef, patch: TaskPatch): Promise<TaskSnapshot> {
    this.calls.push("task.update");
    this.trace.push("task.update");
    this.writeAttempted = true;
    if (this.failWrite) throw new Error("write failed");
    if (!this.mismatch) {
      this.task = Object.freeze({
        ...this.task,
        ...patch,
      });
    }
    return cloneTask(this.task);
  }
}

class FakeCurrentWork implements CurrentWorkPort {
  value: string | null = null;
  failSet = false;
  calls: string[] = [];
  trace: string[];

  constructor(trace: string[] = []) {
    this.trace = trace;
  }

  async getCurrentWorkId(): Promise<string | null> {
    this.calls.push("pointer.get");
    this.trace.push("pointer.get");
    return this.value;
  }

  async setCurrentWorkId(value: string | null): Promise<void> {
    const event = value === null ? "pointer.clear" : "pointer.set";
    this.calls.push(event);
    this.trace.push(event);
    if (this.failSet) throw new Error("pointer write failed");
    this.value = value;
  }
}

const base: TaskSnapshot = Object.freeze({
  calendarId: "tasks",
  uid: "uid-1",
  recurrenceId: "",
  title: "Service acceptance",
  status: "NEEDS-ACTION",
  percentComplete: 20,
  description: "用户描述",
});
const taskId = makeTaskId(base);

async function main(): Promise<void> {
{
  const trace: string[] = [];
  const tasks = new FakeTasks(base, trace);
  const pointer = new FakeCurrentWork(trace);
  const result = await executeTaskCommand("start", taskId, {
    tasks,
    currentWork: pointer,
    nowIso: () => "2026-10-03T19:00:00+08:00",
    newSessionId: () => "session-1",
  });
  assert(result.kind === "committed", "Start should commit");
  assert(pointer.value === taskId, "Start pointer was not retained");
  assert(
    trace.indexOf("pointer.set") < trace.indexOf("task.update"),
    "Start must reserve pointer before VTODO write"
  );
}

let started: TaskSnapshot;
{
  const trace: string[] = [];
  const tasks = new FakeTasks(base, trace);
  const pointer = new FakeCurrentWork(trace);
  const start = await executeTaskCommand("start", taskId, {
    tasks,
    currentWork: pointer,
    nowIso: () => "2026-10-03T19:00:00+08:00",
    newSessionId: () => "session-1",
  });
  assert(start.kind === "committed", "Fixture Start failed");
  started = start.task;

  tasks.calls = [];
  pointer.calls = [];
  const stop = await executeTaskCommand("stop", taskId, {
    tasks,
    currentWork: pointer,
    nowIso: () => "2026-10-03T19:15:00+08:00",
    newSessionId: () => "unused",
  });
  assert(stop.kind === "committed", "Stop should commit");
  assert(pointer.value === null, "Stop pointer was not cleared");
  assert(
    trace.lastIndexOf("task.update") < trace.lastIndexOf("pointer.clear"),
    "Stop must commit VTODO before clearing pointer"
  );
}

{
  const tasks = new FakeTasks(base);
  tasks.mismatch = true;
  const pointer = new FakeCurrentWork();
  const result = await executeTaskCommand("start", taskId, {
    tasks,
    currentWork: pointer,
    nowIso: () => "2026-10-03T19:00:00+08:00",
    newSessionId: () => "session-mismatch",
  });
  assert(result.kind === "failed", "Mismatched Start must fail");
  assert(pointer.value === null, "Mismatched Start must release reserved pointer");
}

{
  const tasks = new FakeTasks(base);
  tasks.failWrite = true;
  tasks.failReadAfterWrite = true;
  const pointer = new FakeCurrentWork();
  const result = await executeTaskCommand("start", taskId, {
    tasks,
    currentWork: pointer,
    nowIso: () => "2026-10-03T19:00:00+08:00",
    newSessionId: () => "session-unknown",
  });
  assert(
    result.kind === "recovery-required" && result.commitState === "unknown",
    "Unverifiable Start must require recovery"
  );
  assert(
    pointer.value === taskId,
    "Unverifiable Start must retain pointer for safe recovery"
  );
}

{
  const tasks = new FakeTasks(started!);
  const pointer = new FakeCurrentWork();
  pointer.value = taskId;
  pointer.failSet = true;
  const result = await executeTaskCommand("complete", taskId, {
    tasks,
    currentWork: pointer,
    nowIso: () => "2026-10-03T19:30:00+08:00",
    newSessionId: () => "unused",
  });
  assert(
    result.kind === "recovery-required" && result.commitState === "committed",
    "Committed Complete with pointer-clear failure must require recovery"
  );
  assert(tasks.task.status === "COMPLETED", "Complete VTODO did not commit");
}

{
  const tasks = new FakeTasks(base);
  const pointer = new FakeCurrentWork();
  pointer.value = taskId;
  const recovered = await reconcileCurrentWork({tasks, currentWork: pointer});
  assert(
    recovered.kind === "cleared-stale-pointer",
    "Pointer without open Description session should be cleared"
  );
  assert(pointer.value === null, "Stale pointer was not cleared");
}

{
  const tasks = new FakeTasks(started!);
  const pointer = new FakeCurrentWork();
  pointer.value = taskId;
  const recovered = await reconcileCurrentWork({tasks, currentWork: pointer});
  assert(recovered.kind === "valid", "Open Description session should validate pointer");
  assert(pointer.value === taskId, "Valid pointer should remain untouched");
}

console.log("workflow-service-harness: PASS");
}

void main();
