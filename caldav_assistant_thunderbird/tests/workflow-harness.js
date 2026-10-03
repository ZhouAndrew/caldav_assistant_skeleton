"use strict";

const fs = require("fs");
const vm = require("vm");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const storage = {};
const storageWrites = [];
const storageRemoves = [];

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
        storageWrites.push(...Object.keys(values));
        Object.assign(storage, values);
      },
      async remove(keys) {
        for (const key of Array.isArray(keys) ? keys : [keys]) {
          storageRemoves.push(key);
          delete storage[key];
        }
      },
    },
  },
};

const tasks = new Map();

function taskKey(calendarId, id, recurrenceId = "") {
  return calendarId + "::" + id + "::" + recurrenceId;
}

function makeTask({
  id = "seed-task",
  calendarId = "tasks",
  title = "Seed task",
  status = "NEEDS-ACTION",
  percentComplete = 0,
  recurrenceId = "",
} = {}) {
  return {
    id,
    calendarId,
    calendarName: "Tasks",
    title,
    status,
    percentComplete,
    recurrenceId,
    instanceKey: taskKey(calendarId, id, recurrenceId),
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function seedTask(value) {
  tasks.set(taskKey(value.calendarId, value.id, value.recurrenceId || ""), value);
  return value;
}

let seed = seedTask(makeTask());
let second = seedTask(makeTask({
  id: "second-task",
  title: "Second task",
}));

const faults = {
  failNextTaskWrite: false,
};

let eventApiCalls = 0;

browser.ThunderbirdCalDAV = {
  async listTasks() {
    return [...tasks.values()].map(clone);
  },

  async updateTask(calendarId, itemId, changes, recurrenceId = "") {
    const key = taskKey(calendarId, itemId, recurrenceId || "");
    const task = tasks.get(key);
    assert(task, "wrong task target");

    if (faults.failNextTaskWrite) {
      faults.failNextTaskWrite = false;
      throw new Error("simulated Thunderbird Task write failure");
    }

    if ("status" in changes) {
      const status = changes.status || "";
      if (status === "COMPLETED") {
        task.status = "COMPLETED";
        task.percentComplete = 100;
      } else {
        task.status = status;
      }
    }
    if ("percentComplete" in changes) {
      task.percentComplete = Number(changes.percentComplete || 0);
    }
    return clone(task);
  },

  async getTask(calendarId, itemId, recurrenceId = "") {
    const task = tasks.get(taskKey(calendarId, itemId, recurrenceId || ""));
    if (!task) throw new Error("Task not found");
    return clone(task);
  },

  async createEvent() {
    eventApiCalls++;
    throw new Error("Task lifecycle must not create VEVENTs");
  },
  async updateEvent() {
    eventApiCalls++;
    throw new Error("Task lifecycle must not update VEVENTs");
  },
  async deleteEvent() {
    eventApiCalls++;
    throw new Error("Task lifecycle must not delete VEVENTs");
  },
};

global.window = global;

for (const script of ["addon/core/storage.js", "addon/core/executor.js"]) {
  vm.runInThisContext(fs.readFileSync(script, "utf8"), {filename: script});
}

function resetAll() {
  for (const key of Object.keys(storage)) delete storage[key];
  storageWrites.length = 0;
  storageRemoves.length = 0;
  tasks.clear();
  seed = seedTask(makeTask());
  second = seedTask(makeTask({id: "second-task", title: "Second task"}));
  faults.failNextTaskWrite = false;
  eventApiCalls = 0;
}

async function normalLifecycle() {
  resetAll();

  let receipt = await AssistantExecutor.start(clone(seed));
  assert(receipt.success, "start failed");
  assert(seed.status === "IN-PROCESS", "Start did not set IN-PROCESS");
  assert(
    await AssistantStorage.getCurrentWorkId() === seed.instanceKey,
    "Start did not persist exactly one current_work_id"
  );
  assert(eventApiCalls === 0, "Start touched VEVENT API");

  receipt = await AssistantExecutor.stop(clone(seed));
  assert(receipt.success, "stop failed");
  assert(seed.status === "NEEDS-ACTION", "Stop did not set NEEDS-ACTION");
  assert(
    await AssistantStorage.getCurrentWorkId() === null,
    "Stop did not clear current_work_id"
  );
  assert(eventApiCalls === 0, "Stop touched VEVENT API");

  receipt = await AssistantExecutor.start(clone(seed));
  assert(receipt.success, "restart failed");
  receipt = await AssistantExecutor.complete(clone(seed));
  assert(receipt.success, "complete failed");
  assert(seed.status === "COMPLETED", "Complete did not set COMPLETED");
  assert(seed.percentComplete === 100, "Complete did not set 100 percent");
  assert(
    await AssistantStorage.getCurrentWorkId() === null,
    "Complete did not clear current_work_id"
  );
  assert(eventApiCalls === 0, "Complete touched VEVENT API");

  const audit = await AssistantStorage.listAudit();
  assert(
    audit.map(row => row.action).join(",") === "start,stop,start,complete",
    "workflow audit sequence is wrong"
  );
}

async function stopPreservesStandardProgress() {
  resetAll();
  seed.percentComplete = 35;

  let receipt = await AssistantExecutor.start(clone(seed));
  assert(receipt.success, "progress Start failed");
  assert(seed.percentComplete === 35, "Start changed existing progress");

  receipt = await AssistantExecutor.stop(clone(seed));
  assert(receipt.success, "progress Stop failed");
  assert(seed.status === "NEEDS-ACTION", "progress Stop status wrong");
  assert(seed.percentComplete === 35, "Stop erased standard VTODO progress");
}

async function startRequiresStopFirst() {
  resetAll();

  let receipt = await AssistantExecutor.start(clone(seed));
  assert(receipt.success, "first Start failed");

  receipt = await AssistantExecutor.start(clone(second));
  assert(!receipt.success, "second Start should require Stop");
  assert(/Stop the current Task/i.test(receipt.error), "wrong second Start error");
  assert(second.status === "NEEDS-ACTION", "blocked Start changed second Task");
  assert(
    await AssistantStorage.getCurrentWorkId() === seed.instanceKey,
    "blocked Start changed current_work_id"
  );
}

async function completeAndCancelDoNotRequireCurrentTask() {
  resetAll();

  let receipt = await AssistantExecutor.complete(clone(second));
  assert(receipt.success, "non-current Complete failed");
  assert(second.status === "COMPLETED", "non-current Complete status wrong");

  const third = seedTask(makeTask({id: "third-task", title: "Third task"}));
  receipt = await AssistantExecutor.cancel(clone(third));
  assert(receipt.success, "non-current Cancel failed");
  assert(third.status === "CANCELLED", "non-current Cancel status wrong");
  assert(await AssistantStorage.getCurrentWorkId() === null, "terminal action invented current work");
}

async function failedStartRollsBackSinglePointer() {
  resetAll();
  faults.failNextTaskWrite = true;

  const receipt = await AssistantExecutor.start(clone(seed));
  assert(!receipt.success, "failed Task write should fail Start");
  assert(seed.status === "NEEDS-ACTION", "failed Start changed Task");
  assert(
    await AssistantStorage.getCurrentWorkId() === null,
    "failed Start left current_work_id"
  );
  assert(
    receipt.steps.some(step =>
      step.component === "Assistant State" &&
      step.operation === "restore current_work_id" &&
      step.success
    ),
    "failed Start did not record pointer rollback"
  );
}

async function reconciliationClearsStalePointer() {
  resetAll();
  await AssistantStorage.setCurrentWorkId(seed.instanceKey);
  seed.status = "NEEDS-ACTION";

  const current = await AssistantExecutor.currentTask();
  assert(current === null, "stale pointer produced a current Task");
  assert(
    await AssistantStorage.getCurrentWorkId() === null,
    "stale pointer was not cleared"
  );
}

async function legacyRuntimeMigratesToOneId() {
  resetAll();
  storage["caldavAssistant.runtime"] = {
    state: "working",
    currentTask: {
      id: seed.id,
      calendarId: seed.calendarId,
      recurrenceId: "",
    },
    currentWorkEvent: {id: "obsolete-work-event", calendarId: "work"},
    segmentStartedAtMs: 123,
    accumulatedMs: 456,
    taskBeforeStart: {status: "NEEDS-ACTION"},
  };

  const value = await AssistantStorage.getCurrentWorkId();
  assert(value === seed.instanceKey, "legacy runtime did not migrate to one instance id");
  assert(
    storage["caldavAssistant.runtime"] === undefined,
    "legacy runtime object was not removed"
  );
  assert(
    storage["caldavAssistant.currentWorkId"] === seed.instanceKey,
    "migrated current_work_id was not persisted"
  );
}

(async () => {
  await normalLifecycle();
  await stopPreservesStandardProgress();
  await startRequiresStopFirst();
  await completeAndCancelDoNotRequireCurrentTask();
  await failedStartRollsBackSinglePointer();
  await reconciliationClearsStalePointer();
  await legacyRuntimeMigratesToOneId();
  console.log("workflow-harness: PASS");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
