import {TaskPatch, TaskSnapshot} from "../src/domain";
import {migrateLegacySettings} from "../src/migration/legacy-settings";
import {ensureV2Settings} from "../src/migration/settings-service";
import {CurrentWorkStore, DiagnosticSink, RawSettingsStore, TaskRepository} from "../src/ports";
import {runTaskCommand} from "../src/task-service";
import {encodeTaskId} from "../src/task-id";
import {parseWorkDescription} from "../src/work-description";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const identity = {
  calendarId: "tasks",
  uid: "uid-service",
  recurrenceId: "",
};
const taskId = encodeTaskId(identity);

function makeTask(): TaskSnapshot {
  return {
    ...identity,
    taskId,
    title: "Service task",
    description: "用户说明",
    status: "NEEDS-ACTION",
    percentComplete: 20,
  };
}

class MemoryTaskRepo implements TaskRepository {
  value: TaskSnapshot | null = makeTask();
  failRead = false;
  failWrite = false;
  ignoreWrite = false;

  async get(id: string): Promise<TaskSnapshot | null> {
    if (this.failRead) throw new Error("read failed");
    if (!this.value || id !== this.value.taskId) return null;
    return Object.freeze({...this.value});
  }

  async update(id: string, patch: TaskPatch): Promise<void> {
    if (this.failWrite) throw new Error("write failed");
    if (!this.value || id !== this.value.taskId) throw new Error("missing");
    if (this.ignoreWrite) return;
    this.value = Object.freeze({
      ...this.value,
      description: patch.description,
      status: patch.status,
      percentComplete: patch.percentComplete,
    });
  }
}

class MemoryPointer implements CurrentWorkStore {
  value: string | null = null;
  failRead = false;
  failWrite = false;

  async get(): Promise<string | null> {
    if (this.failRead) throw new Error("pointer read failed");
    return this.value;
  }

  async set(value: string | null): Promise<void> {
    if (this.failWrite) throw new Error("pointer write failed");
    this.value = value;
  }
}

class ThrowingDiagnostics implements DiagnosticSink {
  async record(): Promise<void> {
    throw new Error("diagnostic sink unavailable");
  }
}

async function testHappyPath(): Promise<void> {
  const tasks = new MemoryTaskRepo();
  const pointer = new MemoryPointer();

  const start = await runTaskCommand(
    {tasks, currentWork: pointer, diagnostics: new ThrowingDiagnostics()},
    "start",
    taskId,
    "2026-10-03T19:00:00+08:00",
    "session-service"
  );
  assert(start.ok, "service Start failed");
  assert(pointer.value === taskId, "pointer was not written after verified Start");

  const started = await tasks.get(taskId);
  assert(started?.status === "IN-PROCESS", "Task was not set IN-PROCESS");
  const parsed = parseWorkDescription(started?.description ?? "");
  assert(parsed.ok, "written Description did not parse");
  assert(parsed.value.userText === "用户说明", "user Description changed");

  const stop = await runTaskCommand(
    {tasks, currentWork: pointer},
    "stop",
    taskId,
    "2026-10-03T19:10:00+08:00",
    "unused"
  );
  assert(stop.ok, "service Stop failed");
  assert(pointer.value === null, "Stop did not clear pointer");
  const stopped = await tasks.get(taskId);
  assert(stopped?.status === "NEEDS-ACTION", "Stop did not restore status");
  assert(stopped?.percentComplete === 20, "Stop did not restore progress");
}

async function testReadbackFailureDoesNotPublishPointer(): Promise<void> {
  const tasks = new MemoryTaskRepo();
  const pointer = new MemoryPointer();
  tasks.ignoreWrite = true;

  const result = await runTaskCommand(
    {tasks, currentWork: pointer},
    "start",
    taskId,
    "2026-10-03T19:20:00+08:00",
    "session-readback"
  );
  assert(!result.ok && result.kind === "readback-failed",
    "read-back mismatch was not detected");
  assert(result.taskWriteAttempted, "write attempt fact was lost");
  assert(!result.taskVerified, "unverified write was marked verified");
  assert(pointer.value === null, "pointer published before read-back verification");
}

async function testPointerFailureKeepsVerifiedTask(): Promise<void> {
  const tasks = new MemoryTaskRepo();
  const pointer = new MemoryPointer();
  pointer.failWrite = true;

  const result = await runTaskCommand(
    {tasks, currentWork: pointer},
    "start",
    taskId,
    "2026-10-03T19:30:00+08:00",
    "session-pointer"
  );
  assert(!result.ok && result.kind === "pointer-write-failed",
    "pointer failure was not surfaced");
  assert(result.taskVerified, "verified VTODO write was not reported");

  const stored = await tasks.get(taskId);
  const parsed = parseWorkDescription(stored?.description ?? "");
  assert(parsed.ok && parsed.value.workLog.sessions[0]?.end === null,
    "verified open session was rolled back after pointer failure");
}

async function testReadFailuresAreResults(): Promise<void> {
  const taskRead = new MemoryTaskRepo();
  const pointer = new MemoryPointer();
  taskRead.failRead = true;
  const a = await runTaskCommand(
    {tasks: taskRead, currentWork: pointer},
    "start",
    taskId,
    "2026-10-03T19:40:00+08:00",
    "session-a"
  );
  assert(!a.ok && a.kind === "task-read-failed",
    "Task read exception escaped command result");

  const pointerRead = new MemoryPointer();
  pointerRead.failRead = true;
  const b = await runTaskCommand(
    {tasks: new MemoryTaskRepo(), currentWork: pointerRead},
    "start",
    taskId,
    "2026-10-03T19:41:00+08:00",
    "session-b"
  );
  assert(!b.ok && b.kind === "pointer-read-failed",
    "pointer read exception escaped command result");
}

class MemorySettingsStore implements RawSettingsStore {
  legacyReads = 0;
  written = null as ReturnType<typeof migrateLegacySettings>["settings"] | null;

  constructor(
    readonly legacy: unknown,
    readonly existing: ReturnType<typeof migrateLegacySettings>["settings"] | null = null
  ) {}

  async getLegacySettings(): Promise<unknown> {
    this.legacyReads++;
    return this.legacy;
  }

  async getV2Settings(): Promise<ReturnType<typeof migrateLegacySettings>["settings"] | null> {
    return this.existing;
  }

  async setV2Settings(settings: ReturnType<typeof migrateLegacySettings>["settings"]): Promise<void> {
    this.written = settings;
  }
}

async function testPasswordMigrationIsExactAndIdempotent(): Promise<void> {
  const store = new MemorySettingsStore({
    wordpress: {
      transport: "application-password",
      baseUrl: "https://example.invalid",
      username: "andrew",
      applicationPassword: "ABCD EFGH IJKL",
      wordpressPath: "/var/www/html/wordpress",
      wpCliCommand: "wp",
      dailyWorkLogEnabled: true,
    },
  });

  const first = await ensureV2Settings(store);
  assert(first.migrated, "legacy settings were not migrated");
  assert(first.settings.wordpress.applicationPassword === "ABCD EFGH IJKL",
    "password was altered during migration");
  assert(store.written?.wordpress.applicationPassword === "ABCD EFGH IJKL",
    "stored migrated password differs from source");

  const existing = store.written;
  assert(existing !== null, "migration did not persist v2 settings");
  const secondStore = new MemorySettingsStore(
    {wordpress: {applicationPassword: "SHOULD-NOT-BE-READ"}},
    existing
  );
  const second = await ensureV2Settings(secondStore);
  assert(!second.migrated, "existing v2 settings should be reused");
  assert(secondStore.legacyReads === 0, "idempotent migration reread legacy secret");
  assert(second.settings.wordpress.applicationPassword === "ABCD EFGH IJKL",
    "existing migrated password changed");
}

(async () => {
  await testHappyPath();
  await testReadbackFailureDoesNotPublishPointer();
  await testPointerFailureKeepsVerifiedTask();
  await testReadFailuresAreResults();
  await testPasswordMigrationIsExactAndIdempotent();
  console.log("clean-room service: PASS");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
