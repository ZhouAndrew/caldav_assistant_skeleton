import {TaskPatch, TaskRef, TaskSnapshot, taskId} from "../src/domain";
import {
  CalendarSummary,
  TaskPort,
  TaskPrecondition,
  TaskQuery,
  TaskRecord,
  TaskWriteResult,
} from "../src/ports";
import {
  CurrentWorkStore,
  createTaskWorkflowService,
} from "../src/workflow-service";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function record(
  ref: TaskRef,
  overrides: Partial<TaskSnapshot> = {},
): TaskRecord {
  return {
    calendarId: ref.calendarId,
    uid: ref.uid,
    recurrenceId: ref.recurrenceId,
    calendarName: "Tasks",
    title: "Task " + ref.uid,
    status: "NEEDS-ACTION",
    percentComplete: 0,
    description: "",
    writable: true,
    priority: 0,
    categories: [],
    start: null,
    due: null,
    completedDate: null,
    recurring: Boolean(ref.recurrenceId),
    ...overrides,
  };
}

function matches(task: TaskRecord, expected: TaskPrecondition): boolean {
  return (
    task.status === expected.status &&
    task.percentComplete === expected.percentComplete &&
    task.description === expected.description
  );
}

class FakeTasks implements TaskPort {
  readonly items = new Map<string, TaskRecord>();
  staleOnce = false;
  corruptReadBack = false;

  constructor(tasks: readonly TaskRecord[]) {
    for (const task of tasks) this.items.set(taskId(task), task);
  }

  async listCalendars(): Promise<readonly CalendarSummary[]> {
    return [];
  }

  async listTasks(_query?: TaskQuery): Promise<readonly TaskRecord[]> {
    return [...this.items.values()];
  }

  async getTask(ref: TaskRef): Promise<TaskRecord> {
    const task = this.items.get(taskId(ref));
    if (!task) throw new Error("missing fake task");
    return task;
  }

  async updateTask(
    ref: TaskRef,
    patch: Readonly<TaskPatch>,
    expected: TaskPrecondition,
  ): Promise<TaskWriteResult> {
    const key = taskId(ref);
    const current = this.items.get(key);
    if (!current) throw new Error("missing fake task");

    if (this.staleOnce) {
      this.staleOnce = false;
      this.items.set(key, {
        ...current,
        description: current.description + "\nuser edit",
      });
      return {ok: false, reason: "changed"};
    }

    if (!matches(current, expected)) {
      return {ok: false, reason: "changed"};
    }

    const next: TaskRecord = {
      ...current,
      ...patch,
    };
    this.items.set(key, next);

    if (this.corruptReadBack) {
      return {
        ok: true,
        task: {...next, description: next.description + " CORRUPTED"},
      };
    }
    return {ok: true, task: next};
  }
}

class FakePointer implements CurrentWorkStore {
  value: string | null = null;
  failNextSet = false;

  async get(): Promise<string | null> {
    return this.value;
  }

  async set(value: string | null): Promise<void> {
    if (this.failNextSet) {
      this.failNextSet = false;
      throw new Error("storage unavailable");
    }
    this.value = value;
  }
}

(async () => {
  const refA = {calendarId: "cal", uid: "A", recurrenceId: ""};
  const refB = {calendarId: "cal", uid: "B", recurrenceId: ""};
  const tasks = new FakeTasks([
    record(refA, {description: "alpha"}),
    record(refB, {description: "beta"}),
  ]);
  const pointer = new FakePointer();
  let ids = 0;
  let clock = 0;

  const service = createTaskWorkflowService({
    tasks,
    currentWork: pointer,
    now: () => new Date(1760000000000 + clock++ * 1000).toISOString(),
    newSessionId: () => "session-" + ++ids,
    staleWriteRetries: 1,
  });

  // Simultaneous Starts are serialized: exactly one Task becomes current.
  const [first, second] = await Promise.all([
    service.start(refA),
    service.start(refB),
  ]);
  assert(first.ok, "first concurrent start should succeed");
  assert(!second.ok, "second concurrent start should be rejected");
  assert(
    !second.ok && second.reason === "current-work-exists",
    "second concurrent start rejection is wrong",
  );
  assert(pointer.value === taskId(refA), "wrong task became current");

  const stop = await service.stop(refA);
  assert(stop.ok, "stop should succeed");
  assert(pointer.value === null, "stop did not clear pointer");

  // A user Description edit between plan and write causes one guarded retry.
  tasks.staleOnce = true;
  const retryStart = await service.start(refA);
  assert(retryStart.ok, "stale write retry did not recover");
  const afterRetry = await tasks.getTask(refA);
  assert(
    afterRetry.description.includes("user edit"),
    "stale retry overwrote the user's Description edit",
  );

  const retryStop = await service.stop(refA);
  assert(retryStop.ok, "stop after stale retry failed");
  const afterRetryStop = await tasks.getTask(refA);
  assert(
    afterRetryStop.description.includes("user edit"),
    "stop lost the user's Description edit",
  );

  // A read-back mismatch is reported as committed; it is never called success.
  tasks.corruptReadBack = true;
  const badReadBack = await service.start(refB);
  assert(!badReadBack.ok, "corrupt read-back was accepted");
  assert(
    !badReadBack.ok &&
      badReadBack.reason === "read-back-mismatch" &&
      badReadBack.committed,
    "read-back mismatch classification is wrong",
  );
  tasks.corruptReadBack = false;

  // Reset the fake committed Task so the next case starts from a coherent state.
  tasks.items.set(taskId(refB), record(refB, {description: "beta"}));
  pointer.value = null;

  // Pointer failure happens after the VTODO commit and must not trigger rollback.
  pointer.failNextSet = true;
  const pointerFailure = await service.start(refB);
  assert(!pointerFailure.ok, "pointer failure was reported as success");
  assert(
    !pointerFailure.ok &&
      pointerFailure.reason === "pointer-write-failed" &&
      pointerFailure.committed,
    "pointer failure classification is wrong",
  );
  const committedTask = await tasks.getTask(refB);
  assert(
    committedTask.status === "IN-PROCESS",
    "pointer failure rolled back the committed VTODO",
  );

  console.log("workflow-service: PASS");
})().catch(error => {
  console.error(error);
  throw error;
});
