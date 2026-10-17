import {StorageArea} from "../src/adapters/browser-storage";
import {TaskPatch, TaskSnapshot} from "../src/domain";
import {migrateLegacyActiveSession} from "../src/migration/legacy-active-session";
import {CurrentWorkStore, TaskRepository} from "../src/ports";
import {encodeTaskId} from "../src/task-id";
import {openWorkSession, parseWorkDescription} from "../src/work-description";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const identity = {calendarId: "tasks", uid: "legacy-1", recurrenceId: ""};
const taskId = encodeTaskId(identity);

function baseTask(): TaskSnapshot {
  return {
    ...identity,
    taskId,
    title: "Legacy active Task",
    description: "用户旧说明",
    status: "IN-PROCESS",
    percentComplete: 35,
  };
}

class Store implements StorageArea {
  constructor(public data: Record<string, unknown>) {}
  async get(keys: string | readonly string[]): Promise<Record<string, unknown>> {
    const list = typeof keys === "string" ? [keys] : [...keys];
    return Object.fromEntries(list.map(key => [key, this.data[key]]));
  }
  async set(values: Record<string, unknown>): Promise<void> {
    Object.assign(this.data, values);
  }
  async remove(keys: string | readonly string[]): Promise<void> {
    for (const key of typeof keys === "string" ? [keys] : keys) {
      delete this.data[key];
    }
  }
}

class Pointer implements CurrentWorkStore {
  constructor(public value: string | null) {}
  async get() { return this.value; }
  async set(value: string | null) { this.value = value; }
}

class Tasks implements TaskRepository {
  value: TaskSnapshot | null = baseTask();
  corruptReadBack = false;
  async get(id: string) {
    if (!this.value || id !== this.value.taskId) return null;
    if (!this.corruptReadBack) return this.value;
    return {...this.value, description: this.value.description + "\nCORRUPTED"};
  }
  async update(id: string, patch: TaskPatch) {
    if (!this.value || id !== this.value.taskId) throw new Error("missing");
    this.value = {...this.value, ...patch};
  }
}

function startAudit() {
  return {
    id: "receipt-start-1",
    timestamp: "2026-10-03T10:00:01+08:00",
    localDate: "2026-10-03",
    scope: "workflow",
    action: "start",
    success: true,
    details: {
      id: "receipt-start-1",
      action: "start",
      success: true,
      startedAt: "2026-10-03T10:00:00+08:00",
      completedAt: "2026-10-03T10:00:01+08:00",
      task: {
        calendarId: "tasks",
        id: "legacy-1",
        recurrenceId: "",
        beforeStatus: "NEEDS-ACTION",
        beforePercentComplete: 20,
      },
    },
  };
}

async function testAuditMigration() {
  const store = new Store({
    "caldavAssistant.auditDates": ["2026-10-03"],
    "caldavAssistant.audit.2026-10-03": [startAudit()],
    "caldavAssistant.runtime": {
      state: "working",
      currentTask: {calendarId: "tasks", id: "legacy-1", recurrenceId: ""},
      segmentStartedAtMs: Date.parse("2026-10-03T10:02:00+08:00"),
      taskBeforeStart: {status: "NEEDS-ACTION", percentComplete: 99},
    },
  });
  const tasks = new Tasks();
  const result = await migrateLegacyActiveSession(
    store,
    tasks,
    new Pointer(taskId)
  );
  assert(result.ok && result.migrated, "audit-backed migration failed");
  const parsed = parseWorkDescription(tasks.value?.description ?? "");
  assert(parsed.ok, "migrated Description is invalid");
  assert(parsed.value.userText === "用户旧说明", "user Description changed");
  const open = openWorkSession(parsed.value);
  assert(open?.start === "2026-10-03T10:00:00+08:00", "audit start time was not preferred");
  assert(open?.before.status === "NEEDS-ACTION", "pre-Start status lost");
  assert(open?.before.percentComplete === 20, "pre-Start progress lost");
  assert(store.data["caldavAssistant.migration.activeSession.v1"] === true,
    "migration marker missing");
  assert(!("caldavAssistant.runtime" in store.data), "legacy runtime was not removed");
}

async function testRuntimeFallback() {
  const startMs = Date.parse("2026-10-03T11:00:00+08:00");
  const store = new Store({
    "caldavAssistant.runtime": {
      state: "working",
      currentTask: {calendarId: "tasks", id: "legacy-1", recurrenceId: ""},
      segmentStartedAtMs: startMs,
      taskBeforeStart: {status: "NEEDS-ACTION", percentComplete: 12},
    },
  });
  const tasks = new Tasks();
  const result = await migrateLegacyActiveSession(store, tasks, new Pointer(taskId));
  assert(result.ok && result.migrated, "runtime fallback migration failed");
  const parsed = parseWorkDescription(tasks.value?.description ?? "");
  assert(parsed.ok, "runtime fallback wrote invalid Description");
  const open = openWorkSession(parsed.value);
  assert(open?.start === new Date(startMs).toISOString(), "runtime start time lost");
  assert(open?.before.percentComplete === 12, "runtime pre-state lost");
}

async function testClosedAuditDoesNotInventSession() {
  const store = new Store({
    "caldavAssistant.auditDates": ["2026-10-03"],
    "caldavAssistant.audit.2026-10-03": [
      startAudit(),
      {
        id: "stop",
        timestamp: "2026-10-03T10:30:00+08:00",
        scope: "workflow",
        action: "stop",
        success: true,
        details: {
          action: "stop",
          success: true,
          completedAt: "2026-10-03T10:30:00+08:00",
          task: {
            calendarId: "tasks",
            id: "legacy-1",
            recurrenceId: "",
          },
        },
      },
    ],
    "caldavAssistant.runtime": {
      state: "working",
      currentTask: {calendarId: "tasks", id: "legacy-1", recurrenceId: ""},
      segmentStartedAtMs: Date.parse("2026-10-03T10:00:00+08:00"),
      taskBeforeStart: {status: "NEEDS-ACTION", percentComplete: 20},
    },
  });
  const tasks = new Tasks();
  const result = await migrateLegacyActiveSession(store, tasks, new Pointer(taskId));
  assert(result.ok && !result.migrated, "closed legacy session was reopened");
  assert(result.reason === "legacy-session-already-closed", "wrong closed-session result");
  assert(tasks.value?.description === "用户旧说明", "closed migration changed Task");
}

async function testUnrecoverableLeavesEverything() {
  const runtime = {
    state: "paused",
    currentTask: {calendarId: "tasks", id: "legacy-1", recurrenceId: ""},
    taskBeforeStart: {status: "NEEDS-ACTION", percentComplete: 20},
  };
  const store = new Store({"caldavAssistant.runtime": runtime});
  const tasks = new Tasks();
  const result = await migrateLegacyActiveSession(store, tasks, new Pointer(taskId));
  assert(!result.ok, "unrecoverable legacy active session reported success");
  assert(result.reason === "legacy-active-session-unrecoverable", "wrong failure reason");
  assert(tasks.value?.description === "用户旧说明", "failed migration changed VTODO");
  assert(store.data["caldavAssistant.runtime"] === runtime, "failed migration removed runtime");
  assert(store.data["caldavAssistant.migration.activeSession.v1"] !== true,
    "failed migration wrote success marker");
}

async function testReadbackFailureDoesNotFinalize() {
  const store = new Store({
    "caldavAssistant.auditDates": ["2026-10-03"],
    "caldavAssistant.audit.2026-10-03": [startAudit()],
    "caldavAssistant.runtime": {state: "working"},
  });
  const tasks = new Tasks();
  tasks.corruptReadBack = true;
  const result = await migrateLegacyActiveSession(store, tasks, new Pointer(taskId));
  assert(!result.ok && result.reason === "migration-readback-failed",
    "bad migration read-back was accepted");
  assert(store.data["caldavAssistant.migration.activeSession.v1"] !== true,
    "bad read-back finalized migration");
  assert("caldavAssistant.runtime" in store.data,
    "bad read-back removed legacy fallback");
}

(async () => {
  await testAuditMigration();
  await testRuntimeFallback();
  await testClosedAuditDoesNotInventSession();
  await testUnrecoverableLeavesEverything();
  await testReadbackFailureDoesNotFinalize();
  console.log("clean-room legacy active migration: PASS");
})().catch(error => {
  console.error(error);
  throw error;
});
