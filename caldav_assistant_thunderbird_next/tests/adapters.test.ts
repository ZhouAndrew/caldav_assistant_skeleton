import {BrowserStorageAdapter, STORAGE_KEYS, StorageArea} from "../src/adapters/browser-storage";
import {
  NativeTaskView,
  NativeTasksApi,
  ThunderbirdTaskRepository,
} from "../src/adapters/thunderbird-task-repository";
import {TaskPatch} from "../src/domain";
import {ensureV2Settings} from "../src/migration/settings-service";
import {encodeTaskId} from "../src/task-id";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

class MemoryStorage implements StorageArea {
  readonly data: Record<string, unknown>;
  constructor(initial: Record<string, unknown> = {}) {
    this.data = {...initial};
  }

  async get(keys: string | readonly string[]): Promise<Record<string, unknown>> {
    const names = typeof keys === "string" ? [keys] : [...keys];
    return Object.fromEntries(names.map(key => [key, this.data[key]]));
  }

  async set(values: Record<string, unknown>): Promise<void> {
    Object.assign(this.data, values);
  }
}

async function testStorageAndPasswordMigration(): Promise<void> {
  const storage = new MemoryStorage({
    [STORAGE_KEYS.legacySettings]: {
      wordpress: {
        transport: "application-password",
        baseUrl: "https://wp.example.invalid",
        username: "legacy-user",
        applicationPassword: "LEGACY PASSWORD WITH SPACES",
        wordpressPath: "/srv/wp",
        wpCliCommand: "wp --allow-root",
        allowUntrustedTls: true,
        dailyWorkLogEnabled: true,
      },
    },
  });
  const adapter = new BrowserStorageAdapter(storage);
  const migrated = await ensureV2Settings(adapter);

  assert(migrated.migrated, "legacy settings were not migrated");
  assert(
    migrated.settings.wordpress.applicationPassword ===
      "LEGACY PASSWORD WITH SPACES",
    "legacy Application Password changed during migration"
  );
  const stored = storage.data[STORAGE_KEYS.settingsV2] as {
    wordpress?: {applicationPassword?: string};
  };
  assert(
    stored.wordpress?.applicationPassword === "LEGACY PASSWORD WITH SPACES",
    "migrated password was not persisted to v2 storage"
  );
  assert(
    storage.data[STORAGE_KEYS.legacySettings] !== undefined,
    "migration destructively removed legacy settings"
  );

  const second = await ensureV2Settings(adapter);
  assert(!second.migrated, "migration was not idempotent");
}

async function testCurrentWorkIdValidation(): Promise<void> {
  const storage = new MemoryStorage();
  const adapter = new BrowserStorageAdapter(storage);
  const valid = encodeTaskId({
    calendarId: "tasks",
    uid: "uid|1",
    recurrenceId: "20261003T090000",
  });

  await adapter.set(valid);
  assert(await adapter.get() === valid, "valid currentWorkId did not round-trip");

  storage.data[STORAGE_KEYS.currentWorkId] = "broken-id";
  let threw = false;
  try {
    await adapter.get();
  } catch {
    threw = true;
  }
  assert(threw, "malformed currentWorkId was silently accepted");
}

class FakeNativeTasks implements NativeTasksApi {
  getCalls: string[][] = [];
  updateCalls: Array<{args: string[]; patch: TaskPatch}> = [];

  readonly task: NativeTaskView = {
    calendarId: "cal/1",
    uid: "uid|42",
    recurrenceId: "20261003T090000",
    title: "Native Task",
    description: "原始说明",
    status: "NEEDS-ACTION",
    percentComplete: 40,
  };

  async getTask(
    calendarId: string,
    uid: string,
    recurrenceId: string
  ): Promise<NativeTaskView | null> {
    this.getCalls.push([calendarId, uid, recurrenceId]);
    return this.task;
  }

  async updateTask(
    calendarId: string,
    uid: string,
    recurrenceId: string,
    patch: TaskPatch
  ): Promise<NativeTaskView> {
    this.updateCalls.push({
      args: [calendarId, uid, recurrenceId],
      patch,
    });
    return {...this.task, ...patch};
  }

  async scanStoredTasks() {
    return {
      tasks: [this.task],
      complete: true,
      failures: [],
    } as const;
  }
}

async function testThunderbirdRepositoryIdentity(): Promise<void> {
  const api = new FakeNativeTasks();
  const repo = new ThunderbirdTaskRepository(api);
  const taskId = encodeTaskId({
    calendarId: "cal/1",
    uid: "uid|42",
    recurrenceId: "20261003T090000",
  });

  const task = await repo.get(taskId);
  assert(task?.taskId === taskId, "repository changed opaque taskId");
  assert(task?.description === "原始说明", "repository lost DESCRIPTION");
  assert(
    JSON.stringify(api.getCalls[0]) ===
      JSON.stringify(["cal/1", "uid|42", "20261003T090000"]),
    "repository lost recurring identity on read"
  );

  const patch: TaskPatch = {
    description: "新说明",
    status: "IN-PROCESS",
    percentComplete: 40,
  };
  await repo.update(taskId, patch);
  assert(api.updateCalls.length === 1, "repository did not issue update");
  assert(
    JSON.stringify(api.updateCalls[0]?.args) ===
      JSON.stringify(["cal/1", "uid|42", "20261003T090000"]),
    "repository lost recurring identity on write"
  );
  assert(api.updateCalls[0]?.patch === patch, "repository rewrote task patch");

  const scan = await repo.scanStored();
  assert(scan.complete, "complete native scan became incomplete");
  assert(scan.tasks.length === 1, "native scan lost Task");
  assert(scan.tasks[0]?.taskId === taskId, "native scan changed Task identity");
}

(async () => {
  await testStorageAndPasswordMigration();
  await testCurrentWorkIdValidation();
  await testThunderbirdRepositoryIdentity();
  console.log("clean-room adapters: PASS");
})().catch(error => {
  console.error(error);
  throw error;
});
