import {TaskPatch, TaskRef, TaskSnapshot} from "../src/domain.js";
import {
  LEGACY_AUDIT_DATES_KEY,
  LEGACY_AUDIT_PREFIX,
  LEGACY_CURRENT_WORK_KEY,
  LEGACY_RUNTIME_KEY,
  migrateLegacyActiveSession,
} from "../src/legacy-active-migration.js";
import {makeTaskId} from "../src/task-id.js";
import {StorageAreaPort, StorageCurrentWork} from "../src/storage-runtime.js";
import {ThunderbirdTaskPort} from "../src/workflow-service.js";
import {getOpenSession, parseWorkDescription} from "../src/work-description.js";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

class FakeStorage implements StorageAreaPort {
  values: Record<string, unknown> = {};
  async get(keys: string | readonly string[]): Promise<Record<string, unknown>> {
    const list = typeof keys === "string" ? [keys] : [...keys];
    return Object.fromEntries(list.map(key => [key, this.values[key]]));
  }
  async set(values: Record<string, unknown>): Promise<void> {
    Object.assign(this.values, values);
  }
  async remove(keys: string | readonly string[]): Promise<void> {
    for (const key of typeof keys === "string" ? [keys] : keys) {
      delete this.values[key];
    }
  }
}

class FakeTasks implements ThunderbirdTaskPort {
  constructor(public task: TaskSnapshot) {}
  async getTask(_ref: TaskRef): Promise<TaskSnapshot> {
    return Object.freeze({...this.task});
  }
  async updateTask(_ref: TaskRef, patch: TaskPatch): Promise<TaskSnapshot> {
    this.task = Object.freeze({...this.task, ...patch});
    return this.task;
  }
}

async function main(): Promise<void> {
  const base: TaskSnapshot = Object.freeze({
    calendarId: "cal",
    uid: "uid",
    recurrenceId: "",
    title: "Legacy active",
    status: "IN-PROCESS",
    percentComplete: 30,
    description: "原来的用户描述",
  });
  const taskId = makeTaskId(base);
  const storage = new FakeStorage();
  storage.values[LEGACY_CURRENT_WORK_KEY] = taskId;
  storage.values[LEGACY_AUDIT_DATES_KEY] = ["2026-10-03"];
  storage.values[LEGACY_AUDIT_PREFIX + "2026-10-03"] = [
    {
      timestamp: "2026-10-03T08:00:01.000Z",
      scope: "workflow",
      action: "start",
      success: true,
      details: {
        id: "receipt-123",
        action: "start",
        success: true,
        startedAt: "2026-10-03T08:00:00.000Z",
        task: {
          id: "uid",
          calendarId: "cal",
          recurrenceId: "",
          beforeStatus: "",
          beforePercentComplete: 30,
        },
      },
    },
  ];

  const tasks = new FakeTasks(base);
  const pointer = new StorageCurrentWork(storage);
  const result = await migrateLegacyActiveSession(storage, tasks, pointer);
  assert(result.kind === "migrated", "Legacy active session should migrate");
  assert(
    await pointer.getCurrentWorkId() === taskId,
    "Migrated currentWorkId was not written"
  );

  const parsed = parseWorkDescription(tasks.task.description);
  assert(parsed.ok, "Migrated Description must parse");
  assert(parsed.userText === base.description, "User Description changed");
  const open = getOpenSession(parsed);
  assert(open?.start === "2026-10-03T08:00:00.000Z", "Start time changed");
  assert(open?.before.status === "", "Absent pre-Start STATUS was not preserved");
  assert(open?.before.percentComplete === 30, "Pre-Start progress changed");

  // Retry after a crash/restart must not append a second session.
  await pointer.setCurrentWorkId(null);
  const retry = await migrateLegacyActiveSession(storage, tasks, pointer);
  assert(
    retry.kind === "already-migrated",
    "Migration retry should recognize the existing open session"
  );
  const retryParsed = parseWorkDescription(tasks.task.description);
  assert(retryParsed.ok && retryParsed.workLog.sessions.length === 1,
    "Migration retry duplicated the session");

  // No trustworthy evidence: do not invent a timestamp or mutate Description.
  const unresolvedStorage = new FakeStorage();
  unresolvedStorage.values[LEGACY_CURRENT_WORK_KEY] = taskId;
  unresolvedStorage.values[LEGACY_RUNTIME_KEY] = {
    currentTask: {calendarId: "cal", id: "uid", recurrenceId: ""},
  };
  const unresolvedTasks = new FakeTasks(base);
  const unresolved = await migrateLegacyActiveSession(
    unresolvedStorage,
    unresolvedTasks,
    new StorageCurrentWork(unresolvedStorage)
  );
  assert(unresolved.kind === "unresolved", "Missing evidence must be unresolved");
  assert(
    unresolvedTasks.task.description === base.description,
    "Unresolved migration must not modify Description"
  );

  console.log("legacy-active-migration-harness: PASS");
}

void main();
