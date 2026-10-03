import {
  TaskPatch,
  TaskRef,
  TaskSnapshot,
  taskId,
} from "../src/domain";
import {
  TaskPort,
  TaskPrecondition,
  TaskQuery,
  TaskRecord,
  TaskWriteResult,
} from "../src/ports";
import {
  CurrentWorkPort,
  executeTaskCommand,
} from "../src/task-service";
import {planTaskAction} from "../src/workflow";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function record(snapshot: TaskSnapshot): TaskRecord {
  return Object.freeze({
    ...snapshot,
    calendarName: "Tasks",
    writable: true,
    priority: 0,
    categories: Object.freeze([]),
    start: null,
    due: null,
    completedDate: null,
    recurring: Boolean(snapshot.recurrenceId),
  });
}

function samePrecondition(task: TaskRecord, expected: TaskPrecondition): boolean {
  return task.status === expected.status &&
    task.percentComplete === expected.percentComplete &&
    task.description === expected.description;
}

class FakeTasks implements TaskPort {
  current: TaskRecord;
  readonly calls: string[] = [];
  forceChanged = false;
  corruptReadBack = false;

  constructor(initial: TaskRecord) {
    this.current = initial;
  }

  async listCalendars() {
    return Object.freeze([]);
  }

  async listTasks(_query?: TaskQuery) {
    return Object.freeze([this.current]);
  }

  async getTask(_ref: TaskRef) {
    this.calls.push("task:get");
    return this.current;
  }

  async updateTask(
    _ref: TaskRef,
    patch: Readonly<TaskPatch>,
    expected: TaskPrecondition,
  ): Promise<TaskWriteResult> {
    this.calls.push("task:update");
    if (this.forceChanged || !samePrecondition(this.current, expected)) {
      return Object.freeze({ok: false, reason: "changed"});
    }

    const next = record({
      ...this.current,
      ...patch,
      status: "status" in patch ? patch.status ?? null : this.current.status,
      percentComplete:
        "percentComplete" in patch
          ? Number(patch.percentComplete)
          : this.current.percentComplete,
      description:
        "description" in patch
          ? String(patch.description ?? "")
          : this.current.description,
    });
    this.current = this.corruptReadBack
      ? record({...next, status: this.current.status})
      : next;
    return Object.freeze({ok: true, task: this.current});
  }
}

class FakeCurrentWork implements CurrentWorkPort {
  value: string | null;
  readonly calls: string[] = [];
  failSet = false;

  constructor(initial: string | null) {
    this.value = initial;
  }

  async getCurrentWorkId() {
    this.calls.push("pointer:get");
    return this.value;
  }

  async setCurrentWorkId(value: string | null) {
    this.calls.push("pointer:set");
    if (this.failSet) throw new Error("simulated pointer write failure");
    this.value = value;
    return this.value;
  }
}

const base: TaskSnapshot = Object.freeze({
  calendarId: "tasks",
  uid: "service-1",
  recurrenceId: "",
  title: "Service integration",
  status: "NEEDS-ACTION",
  percentComplete: 20,
  description: "keep user text",
});

async function main() {
  {
    const tasks = new FakeTasks(record(base));
    const pointer = new FakeCurrentWork(null);
    const result = await executeTaskCommand(
      {tasks, currentWork: pointer},
      {
        intent: "start",
        ref: base,
        now: "2026-10-03T17:40:00+08:00",
        sessionId: "service-session-1",
      },
    );

    assert(result.ok, "service Start failed");
    assert(tasks.current.status === "IN-PROCESS", "Start did not commit VTODO");
    assert(pointer.value === taskId(base), "Start did not publish currentWorkId");
    assert(
      tasks.calls.join(",") === "task:get,task:update",
      "unexpected Task call order",
    );
    assert(
      pointer.calls.join(",") === "pointer:get,pointer:set",
      "unexpected pointer call order",
    );
    assert(
      tasks.calls.indexOf("task:update") >= 0 &&
        pointer.calls.indexOf("pointer:set") >= 0,
      "Start did not execute both durable and pointer writes",
    );
  }

  {
    const tasks = new FakeTasks(record(base));
    tasks.forceChanged = true;
    const pointer = new FakeCurrentWork(null);
    const result = await executeTaskCommand(
      {tasks, currentWork: pointer},
      {
        intent: "start",
        ref: base,
        now: "2026-10-03T17:41:00+08:00",
        sessionId: "service-session-stale",
      },
    );

    assert(!result.ok && result.kind === "write", "stale write was not rejected");
    assert(result.reason === "changed", "wrong stale-write reason");
    assert(pointer.value === null, "stale write published currentWorkId");
    assert(
      pointer.calls.join(",") === "pointer:get",
      "stale write touched pointer storage",
    );
  }

  {
    const tasks = new FakeTasks(record(base));
    tasks.corruptReadBack = true;
    const pointer = new FakeCurrentWork(null);
    let failed = false;
    try {
      await executeTaskCommand(
        {tasks, currentWork: pointer},
        {
          intent: "start",
          ref: base,
          now: "2026-10-03T17:42:00+08:00",
          sessionId: "service-session-bad-readback",
        },
      );
    } catch (error) {
      failed = String(error).includes("read-back");
    }
    assert(failed, "bad VTODO read-back was accepted");
    assert(pointer.value === null, "bad read-back published currentWorkId");
  }

  {
    const tasks = new FakeTasks(record(base));
    const pointer = new FakeCurrentWork(null);
    pointer.failSet = true;
    let failed = false;
    try {
      await executeTaskCommand(
        {tasks, currentWork: pointer},
        {
          intent: "start",
          ref: base,
          now: "2026-10-03T17:43:00+08:00",
          sessionId: "service-session-pointer-fail",
        },
      );
    } catch (error) {
      failed = String(error).includes("pointer write failure");
    }
    assert(failed, "pointer failure was swallowed");
    assert(
      tasks.current.status === "IN-PROCESS",
      "pointer failure incorrectly rolled back verified VTODO",
    );
    assert(
      tasks.current.description.includes("service-session-pointer-fail"),
      "pointer failure lost durable work session",
    );
  }

  {
    const startPlan = planTaskAction({
      intent: "start",
      task: base,
      currentWorkId: null,
      now: "2026-10-03T17:44:00+08:00",
      sessionId: "service-session-stop",
    });
    assert(startPlan.ok, "fixture Start plan failed");
    const started = record({
      ...base,
      status: "IN-PROCESS",
      description: String(startPlan.taskPatch.description),
    });
    const tasks = new FakeTasks(started);
    const pointer = new FakeCurrentWork(taskId(base));

    const result = await executeTaskCommand(
      {tasks, currentWork: pointer},
      {
        intent: "stop",
        ref: base,
        now: "2026-10-03T17:50:00+08:00",
      },
    );
    assert(result.ok, "service Stop failed");
    assert(tasks.current.status === "NEEDS-ACTION", "Stop did not restore status");
    assert(tasks.current.percentComplete === 20, "Stop did not restore progress");
    assert(pointer.value === null, "Stop did not clear currentWorkId");
    assert(result.closedSession?.result === "stop", "Stop lost closed session");
  }

  {
    const tasks = new FakeTasks(record(base));
    const pointer = new FakeCurrentWork(JSON.stringify(["other", "uid", ""]));
    const result = await executeTaskCommand(
      {tasks, currentWork: pointer},
      {
        intent: "start",
        ref: base,
        now: "2026-10-03T17:51:00+08:00",
        sessionId: "must-not-write",
      },
    );
    assert(!result.ok && result.kind === "plan", "conflicting Start not rejected");
    assert(result.reason === "current-work-exists", "wrong conflict reason");
    assert(
      tasks.calls.join(",") === "task:get",
      "plan rejection performed a Task write",
    );
    assert(
      pointer.calls.join(",") === "pointer:get",
      "plan rejection performed a pointer write",
    );
  }

  console.log("task workflow service: PASS");
}

void main();
