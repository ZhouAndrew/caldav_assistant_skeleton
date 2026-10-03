import {TaskPatch, TaskRef, taskId} from "../src/domain";
import {
  LegacyMigrationStore,
  migrateLegacyState,
} from "../src/legacy-migration-service";
import {
  CalendarSummary,
  TaskPort,
  TaskPrecondition,
  TaskQuery,
  TaskRecord,
  TaskWriteResult,
} from "../src/ports";
import {openSessions, parseWorkDescription} from "../src/work-description";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const ref: TaskRef = {
  calendarId: "tasks",
  uid: "legacy-uid",
  recurrenceId: "",
};
const legacyId = [
  encodeURIComponent(ref.calendarId),
  encodeURIComponent(ref.uid),
  "",
].join("|");

function makeTask(description = ""): TaskRecord {
  return {
    ...ref,
    calendarName: "Tasks",
    title: "Legacy active Task",
    status: "IN-PROCESS",
    completed: false,
    percentComplete: 45,
    description,
    writable: true,
    priority: 0,
    categories: [],
    start: null,
    due: null,
    completedDate: null,
    recurring: false,
  };
}

class Tasks implements TaskPort {
  task = makeTask("用户说明 😀");
  staleOnce = false;
  writes = 0;

  async listCalendars(): Promise<readonly CalendarSummary[]> { return []; }
  async listTasks(_q?: TaskQuery): Promise<readonly TaskRecord[]> { return [this.task]; }
  async getTask(_ref: TaskRef): Promise<TaskRecord> { return this.task; }

  async updateTask(
    _ref: TaskRef,
    patch: Readonly<TaskPatch>,
    expected: TaskPrecondition,
  ): Promise<TaskWriteResult> {
    if (this.staleOnce) {
      this.staleOnce = false;
      this.task = {...this.task, description: this.task.description + "\n用户刚改的文字"};
      return {ok: false, reason: "changed"};
    }
    if (
      this.task.status !== expected.status ||
      this.task.completed !== expected.completed ||
      this.task.percentComplete !== expected.percentComplete ||
      this.task.description !== expected.description
    ) {
      return {ok: false, reason: "changed"};
    }
    this.writes++;
    this.task = {...this.task, ...patch};
    return {ok: true, task: this.task};
  }
}

class Store implements LegacyMigrationStore {
  complete = false;
  pointer: unknown = legacyId;
  runtime: unknown = null;
  lastReceipt: unknown = null;
  audit: readonly unknown[] = [];
  runtimeRemoved = false;

  async isComplete() { return this.complete; }
  async getRawCurrentWorkId() { return this.pointer; }
  async getLegacyRuntime() { return this.runtime; }
  async getLastReceipt() { return this.lastReceipt; }
  async listAuditRecords() { return this.audit; }
  async setCurrentWorkId(value: string | null) { this.pointer = value; }
  async removeLegacyRuntime() { this.runtimeRemoved = true; this.runtime = null; }
  async markComplete() { this.complete = true; }
}

(async () => {
  const tasks = new Tasks();
  const store = new Store();
  store.lastReceipt = {
    action: "start",
    success: true,
    startedAt: "2026-10-03T08:00:00+08:00",
    task: {
      calendarId: ref.calendarId,
      id: ref.uid,
      recurrenceId: "",
      beforeStatus: "NEEDS-ACTION",
    },
  };

  const migrated = await migrateLegacyState({
    tasks,
    store,
    newSessionId: () => "migration-session",
    staleWriteRetries: 1,
  });
  assert(migrated.ok && migrated.state === "migrated", "active legacy Task did not migrate");
  assert(migrated.ok && migrated.source === "last-receipt", "migration source wrong");
  assert(store.pointer === taskId(ref), "legacy pointer was not converted");
  assert(store.complete, "migration marker was not written");
  assert(store.runtimeRemoved, "legacy runtime was not removed");
  assert(tasks.writes === 1, "migration wrote the Task unexpected number of times");
  const parsed = parseWorkDescription(tasks.task.description);
  assert(parsed.ok, "migrated Description is invalid");
  assert(parsed.value.prefix.startsWith("用户说明 😀"), "user Description was lost");
  const open = openSessions(parsed.value);
  assert(open.length === 1, "migration did not create one open session");
  assert(open[0]?.start === "2026-10-03T00:00:00.000Z", "legacy Start time was lost");
  assert(open[0]?.before.status === "NEEDS-ACTION", "legacy pre-Start STATUS was lost");

  // Re-running after the marker is a no-op.
  const again = await migrateLegacyState({
    tasks,
    store,
    newSessionId: () => "must-not-run",
  });
  assert(again.ok && again.state === "already-complete", "migration was not one-time");
  assert(tasks.writes === 1, "completed migration rewrote VTODO");

  // A concurrent user Description edit is preserved by guarded retry.
  const staleTasks = new Tasks();
  staleTasks.staleOnce = true;
  const staleStore = new Store();
  staleStore.lastReceipt = store.lastReceipt;
  const stale = await migrateLegacyState({
    tasks: staleTasks,
    store: staleStore,
    newSessionId: () => "stale-session",
    staleWriteRetries: 1,
  });
  assert(stale.ok, "migration did not retry a stale Task write");
  assert(
    staleTasks.task.description.includes("用户刚改的文字"),
    "migration overwrote concurrent user Description edit",
  );

  // Missing trustworthy Start time blocks migration and leaves legacy data intact.
  const blockedTasks = new Tasks();
  const blockedStore = new Store();
  const blocked = await migrateLegacyState({
    tasks: blockedTasks,
    store: blockedStore,
    newSessionId: () => "unused",
  });
  assert(!blocked.ok && blocked.reason === "start-fact-missing", "missing Start fact was guessed");
  assert(blockedStore.pointer === legacyId, "blocked migration destroyed legacy pointer");
  assert(!blockedStore.complete, "blocked migration was marked complete");
  assert(!blockedStore.runtimeRemoved, "blocked migration removed fallback data");
  assert(blockedTasks.writes === 0, "blocked migration changed VTODO");

  // No active work is a cheap cleanup: no Task read/write is needed.
  const idleTasks = new Tasks();
  let reads = 0;
  idleTasks.getTask = async () => { reads++; throw new Error("must not read"); };
  const idleStore = new Store();
  idleStore.pointer = null;
  const idle = await migrateLegacyState({
    tasks: idleTasks,
    store: idleStore,
    newSessionId: () => "unused",
  });
  assert(idle.ok && idle.state === "idle", "idle migration failed");
  assert(reads === 0, "idle migration read a Task");
  assert(idleStore.complete && idleStore.runtimeRemoved, "idle migration did not clean legacy state");

  console.log("legacy-migration-service: PASS");
})().catch(error => {
  console.error(error);
  throw error;
});
