import {startCleanroom} from "../src/startup.js";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

class FakeStorageLocal {
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

async function main(): Promise<void> {
  const storage = new FakeStorageLocal();
  const secret = "existing-app-password";
  storage.values["caldavAssistant.settings"] = {
    taskView: "all",
    taskCalendarId: "cal",
    wordpress: {
      transport: "application-password",
      baseUrl: "https://example.local",
      username: "andrew",
      applicationPassword: secret,
      dailyWorkLogEnabled: true,
      allowUntrustedTls: true,
      wordpressPath: "/var/www/html/wordpress",
      wpCliCommand: "wp",
    },
  };

  const browserApi = {
    storage: {local: storage},
    ThunderbirdTasks: {
      async getTask(): Promise<unknown> {
        throw new Error("No Task should be read while startup is idle.");
      },
      async updateTask(): Promise<unknown> {
        throw new Error("No Task should be written while startup is idle.");
      },
    },
  };

  const report = await startCleanroom(browserApi);
  assert(report.settings.migrated, "Startup should migrate old settings once");
  assert(
    report.settings.settings.wordpress.applicationPassword === secret,
    "Startup lost the existing WordPress password"
  );
  assert(report.legacyActive.kind === "none", "Idle startup invented legacy work");
  assert(report.currentWork?.kind === "idle", "Idle startup did not reconcile idle");

  const second = await startCleanroom(browserApi);
  assert(!second.settings.migrated, "Startup migration must be idempotent");
  assert(
    second.settings.settings.wordpress.applicationPassword === secret,
    "Second startup lost the migrated password"
  );

  console.log("startup-harness: PASS");
}

void main();
