import {
  CURRENT_WORK_KEY,
  LEGACY_SETTINGS_KEY,
  SETTINGS_KEY,
  StorageAreaPort,
  StorageCurrentWork,
  loadOrMigrateSettings,
  saveSettings,
} from "../src/storage-runtime";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

class FakeStorage implements StorageAreaPort {
  values: Record<string, unknown> = {};
  removed: string[] = [];

  async get(keys: string | readonly string[]): Promise<Record<string, unknown>> {
    const names = typeof keys === "string" ? [keys] : [...keys];
    return Object.fromEntries(names.map(key => [key, this.values[key]]));
  }

  async set(values: Record<string, unknown>): Promise<void> {
    Object.assign(this.values, values);
  }

  async remove(keys: string | readonly string[]): Promise<void> {
    const names = typeof keys === "string" ? [keys] : [...keys];
    for (const key of names) {
      delete this.values[key];
      this.removed.push(key);
    }
  }
}

async function main(): Promise<void> {
  const secret = "migrate-this-secret-exactly";
  const storage = new FakeStorage();
  storage.values[LEGACY_SETTINGS_KEY] = {
    taskView: "all",
    taskCalendarId: "tasks-1",
    workCalendarId: "must-not-migrate",
    wordpress: {
      dailyWorkLogEnabled: true,
      transport: "application-password",
      baseUrl: "https://example.local",
      username: "andrew",
      applicationPassword: secret,
      allowUntrustedTls: true,
      wordpressPath: "/var/www/html/wordpress",
      wpCliCommand: "wp",
    },
  };

  const first = await loadOrMigrateSettings(storage);
  assert(first.migrated, "First load should migrate settings");
  assert(first.settings.schemaVersion === 1, "Settings schema version missing");
  assert(
    first.settings.wordpress.applicationPassword === secret,
    "Stored Application Password changed during migration"
  );
  assert(
    !JSON.stringify(first.diagnostic).includes(secret),
    "Migration diagnostic leaked Application Password"
  );
  assert(
    storage.values[LEGACY_SETTINGS_KEY] !== undefined,
    "Legacy settings must remain until all migration phases finish"
  );

  const edited = Object.freeze({
    ...first.settings,
    taskView: "incomplete",
  });
  await saveSettings(storage, edited);

  // A second startup must use the new key and must not overwrite user edits
  // from the still-present legacy settings.
  const second = await loadOrMigrateSettings(storage);
  assert(!second.migrated, "Second load should not migrate again");
  assert(second.settings.taskView === "incomplete", "Migration was not idempotent");
  assert(
    second.settings.wordpress.applicationPassword === secret,
    "Password was lost after idempotent reload"
  );

  const pointer = new StorageCurrentWork(storage);
  assert((await pointer.getCurrentWorkId()) === null, "Pointer should start empty");
  await pointer.setCurrentWorkId("calendar|uid|");
  assert(
    storage.values[CURRENT_WORK_KEY] === "calendar|uid|",
    "Pointer was not stored"
  );
  assert(
    (await pointer.getCurrentWorkId()) === "calendar|uid|",
    "Pointer read-back failed"
  );
  await pointer.setCurrentWorkId(null);
  assert((await pointer.getCurrentWorkId()) === null, "Pointer was not cleared");
  assert(
    !Object.prototype.hasOwnProperty.call(storage.values, CURRENT_WORK_KEY),
    "Null pointer should remove its storage key"
  );
  assert(storage.removed.includes(CURRENT_WORK_KEY), "Pointer clear was not explicit");

  assert(
    Object.prototype.hasOwnProperty.call(storage.values, SETTINGS_KEY),
    "New settings key was not persisted"
  );

  console.log("storage-runtime-harness: PASS");
}

void main();
