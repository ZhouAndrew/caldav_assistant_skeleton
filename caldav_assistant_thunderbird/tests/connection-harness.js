"use strict";

const fs = require("fs");
const vm = require("vm");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const storage = {};
const writes = [];
global.browser = {
  storage: {
    local: {
      async get(key) {
        if (typeof key === "string") return {[key]: storage[key]};
        const result = {};
        for (const name of key || []) result[name] = storage[name];
        return result;
      },
      async set(values) {
        writes.push(...Object.keys(values));
        Object.assign(storage, values);
      },
    },
  },
};

global.performance = global.performance || require("perf_hooks").performance;
delete global.AssistantExecutor;

let createTaskCalls = 0;
let nextEvent = 1;
const events = new Map();

browser.ThunderbirdCalDAV = {
  async listCalendars() {
    return [
      {
        id: "work",
        name: "Work",
        supportsTasks: true,
        supportsEvents: true,
        disabled: false,
        readOnly: false,
      },
    ];
  },
  async listTasks() {
    return [{id: "existing-task", title: "Existing Task"}];
  },
  async createTask() {
    createTaskCalls++;
    throw new Error("connection test must never create a VTODO");
  },
  async createEvent(calendarId, values) {
    const event = {
      id: "test-event-" + nextEvent++,
      calendarId,
      calendarName: "Work",
      title: values.title,
      start: {icalString: values.start},
      end: values.end ? {icalString: values.end} : null,
    };
    events.set(event.id, event);
    return JSON.parse(JSON.stringify(event));
  },
  async getEvent(calendarId, itemId) {
    const event = events.get(itemId);
    if (!event || event.calendarId !== calendarId) throw new Error("Calendar item not found");
    return JSON.parse(JSON.stringify(event));
  },
  async updateEvent(calendarId, itemId, changes) {
    const event = events.get(itemId);
    if (!event || event.calendarId !== calendarId) throw new Error("Calendar item not found");
    if ("title" in changes) event.title = changes.title;
    return JSON.parse(JSON.stringify(event));
  },
  async deleteEvent(calendarId, itemId) {
    const event = events.get(itemId);
    if (!event || event.calendarId !== calendarId) throw new Error("Calendar item not found");
    events.delete(itemId);
    return {ok: true};
  },
};

global.window = global;
for (const script of ["addon/core/storage.js", "addon/core/connection.js"]) {
  vm.runInThisContext(fs.readFileSync(script, "utf8"), {filename: script});
}

(async () => {
  let result = await AssistantConnection.quickCalendarTest();
  assert(result.success, "quick Calendar read test failed");
  assert(result.logSaved === true, "quick test was not logged before return");

  writes.length = 0;
  assert(
    typeof global.AssistantExecutor === "undefined",
    "connection test unexpectedly depends on AssistantExecutor"
  );
  result = await AssistantConnection.fullCalendarWriteTest("work");
  assert(result.success, "full Calendar read/write test failed without AssistantExecutor");
  assert(createTaskCalls === 0, "full Calendar test created a VTODO");
  assert(events.size === 0, "full Calendar test left TEST VEVENT data behind");
  assert(
    result.steps.some(step => step.name === "create TEST VEVENT"),
    "full test did not create a temporary VEVENT"
  );
  assert(
    result.steps.some(step => step.name === "update + read-back TEST VEVENT"),
    "full test did not update and read back"
  );
  assert(
    result.steps.some(step => step.name === "delete + absence verification"),
    "full test did not verify deletion"
  );

  const auditIndex = writes.findIndex(key => key.startsWith("caldavAssistant.audit."));
  const receiptIndex = writes.indexOf("caldavAssistant.lastReceipt");
  assert(
    auditIndex >= 0 && receiptIndex >= 0 && auditIndex < receiptIndex,
    "connection test displayed/cached result before persistent log write"
  );

  console.log("connection-harness: PASS");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
