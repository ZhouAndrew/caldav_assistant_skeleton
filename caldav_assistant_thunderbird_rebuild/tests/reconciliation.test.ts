import {TaskRef, TaskSnapshot, taskId} from "../src/domain";
import {TaskRecord} from "../src/ports";
import {
  decidePointer,
  reconcileCurrentWork,
} from "../src/reconciliation";
import {planTaskAction} from "../src/workflow";
import {CurrentWorkStore} from "../src/workflow-service";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function snapshot(
  ref: TaskRef,
  description = "",
): TaskSnapshot {
  return Object.freeze({
    ...ref,
    title: "Recovery Task",
    status: "IN-PROCESS",
    completed: false,
    percentComplete: 20,
    description,
  });
}

function record(task: TaskSnapshot): TaskRecord {
  return {
    ...task,
    calendarName: "Tasks",
    writable: true,
    priority: 0,
    categories: [],
    start: null,
    due: null,
    completedDate: null,
    recurring: Boolean(task.recurrenceId),
  };
}

class Pointer implements CurrentWorkStore {
  value: string | null;
  failClear = false;

  constructor(value: string | null) {
    this.value = value;
  }

  async get(): Promise<string | null> {
    return this.value;
  }

  async set(value: string | null): Promise<void> {
    if (this.failClear && value === null) throw new Error("storage failed");
    this.value = value;
  }
}

(async () => {
  const ref = {
    calendarId: "calendar",
    uid: "uid",
    recurrenceId: "20261003T090000Z",
  };
  const id = taskId(ref);

  let reads = 0;
  const idleStore = new Pointer(null);
  const idle = await reconcileCurrentWork(
    {
      async getTask() {
        reads++;
        throw new Error("must not read");
      },
    },
    idleStore,
  );
  assert(idle.ok && idle.state === "idle", "null pointer was not idle");
  assert(reads === 0, "idle reconciliation scanned/read a Task");

  const reservedTask = snapshot(ref);
  const reservedDecision = decidePointer(id, reservedTask);
  assert(
    reservedDecision.kind === "clear",
    "reserved pointer without VTODO session should clear",
  );

  const start = planTaskAction({
    intent: "start",
    task: {...reservedTask, status: "NEEDS-ACTION"},
    currentWorkId: id,
    now: "2026-10-03T18:00:00+08:00",
    sessionId: "recovery-session",
  });
  assert(start.ok, "could not build open-session fixture");
  const activeTask = snapshot(ref, String(start.taskPatch.description));

  const activeStore = new Pointer(id);
  const active = await reconcileCurrentWork(
    {async getTask() { return record(activeTask); }},
    activeStore,
  );
  assert(active.ok && active.state === "active", "open session was not kept");
  assert(activeStore.value === id, "active pointer changed");

  const stop = planTaskAction({
    intent: "stop",
    task: activeTask,
    currentWorkId: id,
    now: "2026-10-03T18:10:00+08:00",
  });
  assert(stop.ok, "could not build closed-session fixture");
  const closedTask = snapshot(ref, String(stop.taskPatch.description));
  const closedStore = new Pointer(id);
  const closed = await reconcileCurrentWork(
    {async getTask() { return record(closedTask); }},
    closedStore,
  );
  assert(
    closed.ok && closed.state === "cleared-stale",
    "closed session did not clear stale pointer",
  );
  assert(closedStore.value === null, "closed-session pointer was not cleared");

  const badStore = new Pointer("not-json");
  const bad = await reconcileCurrentWork(
    {async getTask() { throw new Error("must not read invalid ref"); }},
    badStore,
  );
  assert(
    bad.ok && bad.state === "cleared-stale" && badStore.value === null,
    "invalid pointer was not cleared",
  );

  const unreadableStore = new Pointer(id);
  const unreadable = await reconcileCurrentWork(
    {async getTask() { throw new Error("provider offline"); }},
    unreadableStore,
  );
  assert(
    !unreadable.ok && unreadable.reason === "task-unreadable",
    "temporary Task read failure was not blocked",
  );
  assert(
    unreadableStore.value === id,
    "temporary Task read failure destroyed currentWorkId",
  );

  const malformedStore = new Pointer(id);
  const malformed = await reconcileCurrentWork(
    {
      async getTask() {
        return record(snapshot(
          ref,
          "[CALDAV-ASSISTANT-WORKLOG v1]\n{broken",
        ));
      },
    },
    malformedStore,
  );
  assert(
    !malformed.ok && malformed.reason === "description-invalid",
    "malformed Description was not blocked",
  );
  assert(malformedStore.value === id, "malformed Description cleared pointer");

  const clearFailureStore = new Pointer(id);
  clearFailureStore.failClear = true;
  const clearFailure = await reconcileCurrentWork(
    {async getTask() { return record(reservedTask); }},
    clearFailureStore,
  );
  assert(
    !clearFailure.ok && clearFailure.reason === "pointer-write-failed",
    "pointer clear failure was not surfaced",
  );
  assert(clearFailureStore.value === id, "failed pointer clear changed memory state");

  console.log("reconciliation: PASS");
})().catch(error => {
  console.error(error);
  throw error;
});
