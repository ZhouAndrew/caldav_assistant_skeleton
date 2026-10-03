import {
  CURRENT_WORK_KEY,
  SETTINGS_KEY,
} from "../src/storage-runtime.js";
import {
  loadTaskPage,
  loadTaskPickerPage,
  runTaskPageAction,
} from "../src/ui-service.js";
import {makeTaskId} from "../src/task-id.js";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

class RecordingStorage {
  values: Record<string, unknown> = {};
  reads: string[] = [];

  async get(keys: string | readonly string[]): Promise<Record<string, unknown>> {
    const list = typeof keys === "string" ? [keys] : [...keys];
    this.reads.push(...list);
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
  const storage = new RecordingStorage();
  storage.values[SETTINGS_KEY] = {
    schemaVersion: 1,
    taskView: "incomplete",
    taskCalendarId: "cal",
    wordpress: {
      dailyWorkLogEnabled: true,
      transport: "auto",
      baseUrl: "",
      username: "",
      applicationPassword: "",
      allowUntrustedTls: false,
      wordpressPath: "/var/www/html/wordpress",
      wpCliCommand: "wp",
    },
  };
  storage.values[CURRENT_WORK_KEY] = "must-not-be-read-by-picker";

  let task = {
    calendarId: "cal",
    uid: "uid",
    recurrenceId: "",
    title: "Picker Task",
    status: "NEEDS-ACTION",
    percentComplete: 0,
    description: "用户描述",
  };

  const browserApi = {
    storage: {local: storage},
    ThunderbirdTasks: {
      async listTasks(): Promise<unknown> {
        return [task];
      },
      async getTask(): Promise<unknown> {
        return task;
      },
      async updateTask(
        _calendarId: string,
        _uid: string,
        _recurrenceId: string,
        patch: Record<string, unknown>
      ): Promise<unknown> {
        task = {...task, ...patch} as typeof task;
        return task;
      },
    },
  };

  const picker = await loadTaskPickerPage(browserApi);
  assert(picker.items.length === 1, "Picker did not load Tasks");
  assert(
    !storage.reads.includes(CURRENT_WORK_KEY),
    "Task Picker must not read currentWorkId"
  );

  storage.reads = [];
  const taskId = makeTaskId(task);
  const page = await loadTaskPage(
    browserApi,
    taskId,
    "2026-10-03T20:00:00+08:00"
  );
  assert(page.actions[0] === "start", "Task Page should offer Start");
  assert(
    storage.reads.includes(CURRENT_WORK_KEY),
    "Task Page must read currentWorkId"
  );

  const started = await runTaskPageAction(
    browserApi,
    "start",
    taskId,
    "2026-10-03T20:00:00+08:00",
    "ui-session"
  );
  assert(started.kind === "committed", "Task Page Start did not commit");

  const after = await loadTaskPage(
    browserApi,
    taskId,
    "2026-10-03T20:10:00+08:00"
  );
  assert(
    JSON.stringify(after.actions) ===
      JSON.stringify(["stop", "complete", "cancel"]),
    "Task Page did not switch to current actions"
  );

  console.log("ui-service-harness: PASS");
}

void main();
