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

async function runCase({migrationOk = true}) {
  const calls = [];
  const writes = [];
  const listeners = {installed: null, startup: null};

  class BrowserStorageAdapter {
    constructor(area) {
      this.area = area;
    }
  }
  class ThunderbirdTaskRepository {
    constructor(api) {
      this.api = api;
    }
  }

  const Core = {
    BrowserStorageAdapter,
    ThunderbirdTaskRepository,
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
  };

  const browser = {
    NativeTasks: {},
    storage: {
      local: {
        async set(value) {
          writes.push(value);
        },
      },
    },
    runtime: {
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

  return {calls, writes, listeners, errors};
}

(async () => {
  const success = await runCase({migrationOk: true});
  assert(
    success.calls.join(",") === "settings,active-migration,recovery",
    "startup ordering is wrong"
  );
  assert(success.writes.length === 1, "ready status was not written exactly once");
  const serialized = JSON.stringify(success.writes);
  assert(!serialized.includes("SECRET-MUST-NOT-LEAK"), "startup leaked password");
  assert(!serialized.includes('"settings"'), "startup leaked settings object");
  assert(serialized.includes('"stage":"ready"'), "ready status missing");

  const blocked = await runCase({migrationOk: false});
  assert(
    blocked.calls.join(",") === "settings,active-migration",
    "recovery ran after failed legacy migration"
  );
  assert(
    JSON.stringify(blocked.writes).includes("legacy-active-session-migration"),
    "failed migration stage was not visible"
  );

  console.log("background startup harness: PASS");
})().catch(error => {
  console.error(error);
  throw error;
});
