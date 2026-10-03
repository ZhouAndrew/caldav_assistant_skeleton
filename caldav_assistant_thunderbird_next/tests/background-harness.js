"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function flush() {
  await new Promise(resolve => setTimeout(resolve, 0));
  await new Promise(resolve => setTimeout(resolve, 0));
}

async function runCase({migrationOk = true, existingSpace = false}) {
  const calls = [];
  const writes = [];
  const storageData = {};
  const listeners = {installed: null, startup: null, message: null};
  let queueRuns = 0;
  const spaceCalls = [];

  class BrowserStorageAdapter {
    constructor(area) {
      this.area = area;
      this.current = "current-task";
    }
    async get() {
      return this.current;
    }
    async set(value) {
      this.current = value;
    }
  }

  class ThunderbirdTaskRepository {
    constructor(api) {
      this.api = api;
    }
    async get(taskId) {
      return taskId === "task-1"
        ? {
            taskId,
            calendarId: "cal",
            uid: "uid",
            recurrenceId: "",
            title: "Task 1",
            description: "Description",
            status: "NEEDS-ACTION",
            percentComplete: 0,
          }
        : null;
    }
    async listCalendars() {
      return [{
        id: "cal",
        name: "Tasks",
        disabled: false,
        inComposite: true,
        readOnly: false,
      }];
    }
    async query() {
      return {
        items: [{
          taskId: "task-1",
          calendarId: "cal",
          calendarName: "Tasks",
          title: "Task 1",
          status: "NEEDS-ACTION",
          percentComplete: 0,
          due: null,
          categories: [],
        }],
        complete: true,
        failures: [],
      };
    }
    async scanStored() {
      return {
        tasks: [],
        complete: true,
        failures: [],
      };
    }
  }

  class SerialCommandQueue {
    async run(operation) {
      queueRuns++;
      return operation();
    }
  }

  const Core = {
    BrowserStorageAdapter,
    ThunderbirdTaskRepository,
    SerialCommandQueue,
    async ensureV2Settings() {
      calls.push("settings");
      return {
        migrated: true,
        settings: {
          wordpress: {
            applicationPassword: "SECRET-MUST-NOT-LEAK",
          },
        },
      };
    },
    async migrateLegacyActiveSession() {
      calls.push("active-migration");
      return migrationOk
        ? {ok: true, migrated: true, reason: "migrated"}
        : {ok: false, migrated: false, reason: "cannot-migrate"};
    },
    async recoverCurrentWork() {
      calls.push("recovery");
      return {
        ok: true,
        changed: true,
        message: "set",
      };
    },
    deriveTaskPickerView(_options, items) {
      return {items, filter: "open", emptyMessageKey: null};
    },
    deriveTaskPageView(task, currentWorkId) {
      return {taskId: task.taskId, currentWorkId};
    },
    deriveTodayView(_tasks, date) {
      return {date, rows: [], warnings: []};
    },
    async runTaskCommand(_deps, intent, taskId) {
      calls.push("command:" + intent + ":" + taskId);
      return {
        ok: true,
        taskId,
        intent,
        currentWorkId: intent === "start" ? taskId : null,
        closedSession: null,
      };
    },
  };

  const browser = {
    NativeTasks: {},
    storage: {
      local: {
        async get(keys) {
          const list = typeof keys === "string" ? [keys] : keys;
          return Object.fromEntries(
            (list || Object.keys(storageData)).map(key => [key, storageData[key]])
          );
        },
        async set(value) {
          Object.assign(storageData, value);
          writes.push(value);
        },
        async remove(keys) {
          for (const key of typeof keys === "string" ? [keys] : keys) {
            delete storageData[key];
          }
        },
      },
    },
    i18n: {
      getMessage(key) {
        return key === "extensionName"
          ? "CalDAV Assistant Experimental"
          : "";
      },
    },
    spaces: {
      async query(info) {
        spaceCalls.push({op: "query", info});
        return existingSpace
          ? [{id: 7, name: "caldav_assistant", isSelfOwned: true}]
          : [];
      },
      async create(name, url, buttonProperties) {
        spaceCalls.push({op: "create", name, url, buttonProperties});
        return {id: 8, name, isSelfOwned: true};
      },
      async update(id, url, buttonProperties) {
        spaceCalls.push({op: "update", id, url, buttonProperties});
        return {id, name: "caldav_assistant", isSelfOwned: true};
      },
    },
    runtime: {
      getURL(path) {
        return "moz-extension://test/" + path;
      },
      onInstalled: {
        addListener(fn) {
          listeners.installed = fn;
        },
      },
      onStartup: {
        addListener(fn) {
          listeners.startup = fn;
        },
      },
      onMessage: {
        addListener(fn) {
          listeners.message = fn;
        },
      },
    },
  };

  const errors = [];
  const context = {
    CalDAVAssistantCore: Core,
    browser,
    console: {
      error(...args) {
        errors.push(args.map(String).join(" "));
      },
      log() {},
      warn() {},
    },
    setTimeout,
    clearTimeout,
  };
  vm.createContext(context);

  const source = fs.readFileSync(
    path.join(__dirname, "..", "addon", "background.js"),
    "utf8"
  );
  vm.runInContext(source, context, {filename: "background.js"});
  await flush();

  return {
    calls,
    writes,
    listeners,
    errors,
    spaceCalls,
    get queueRuns() {
      return queueRuns;
    },
  };
}

(async () => {
  const success = await runCase({migrationOk: true});
  assert(
    success.calls.slice(0, 3).join(",") === "settings,active-migration,recovery",
    "startup ordering is wrong"
  );
  assert(success.writes.length === 1, "ready status was not written exactly once");
  assert(
    success.spaceCalls.some(call => call.op === "create"),
    "first startup did not create Thunderbird Space"
  );
  assert(
    !success.spaceCalls.some(call => call.op === "update"),
    "first startup unexpectedly updated existing Space"
  );
  const serialized = JSON.stringify(success.writes);
  assert(!serialized.includes("SECRET-MUST-NOT-LEAK"), "startup leaked password");
  assert(!serialized.includes('"settings"'), "startup leaked settings object");
  assert(serialized.includes('"stage":"ready"'), "ready status missing");
  assert(typeof success.listeners.message === "function", "RPC listener missing");

  const startupStatus = await success.listeners.message({type: "startup.status"});
  assert(startupStatus.ok, "startup.status failed");
  assert(startupStatus.status?.stage === "ready", "startup.status lost ready state");

  const read = await success.listeners.message({
    type: "task.read",
    taskId: "task-1",
  });
  assert(read.ok && read.view.taskId === "task-1", "task.read failed");

  const command = await success.listeners.message({
    type: "task.command",
    taskId: "task-1",
    intent: "start",
  });
  assert(command.ok && command.result?.ok, "task.command failed");
  assert(success.queueRuns === 1, "task.command bypassed serialized queue");

  const calendars = await success.listeners.message({
    type: "calendars.list",
  });
  assert(
    calendars.ok && calendars.calendars[0]?.id === "cal",
    "calendars.list failed"
  );

  const query = await success.listeners.message({
    type: "tasks.query",
    options: {filter: "open", search: "", calendarIds: []},
  });
  assert(query.ok && query.view.items.length === 1, "tasks.query failed");

  const today = await success.listeners.message({
    type: "today.read",
    date: "2026-10-03",
  });
  assert(today.ok && today.view.date === "2026-10-03", "today.read failed");

  const rpcSerialized = JSON.stringify({
    startupStatus,
    read,
    command,
    calendars,
    query,
    today,
  });
  assert(
    !rpcSerialized.includes("SECRET-MUST-NOT-LEAK"),
    "background RPC leaked Application Password"
  );


  const existingSpace = await runCase({
    migrationOk: true,
    existingSpace: true,
  });
  assert(
    existingSpace.spaceCalls.some(call => call.op === "update"),
    "existing Space was not updated idempotently"
  );
  assert(
    !existingSpace.spaceCalls.some(call => call.op === "create"),
    "existing Space was duplicated"
  );

  const blocked = await runCase({migrationOk: false});
  assert(
    blocked.calls.join(",") === "settings,active-migration",
    "recovery ran after failed legacy migration"
  );
  assert(
    JSON.stringify(blocked.writes).includes("legacy-active-session-migration"),
    "failed migration stage was not visible"
  );
  const blockedRpc = await blocked.listeners.message({
    type: "task.read",
    taskId: "task-1",
  });
  assert(
    !blockedRpc.ok && blockedRpc.error?.code === "startup-not-ready",
    "RPC bypassed failed startup migration"
  );

  console.log("background startup/RPC harness: PASS");
})().catch(error => {
  console.error(error);
  throw error;
});
