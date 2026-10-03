"use strict";

const fs = require("fs");
const vm = require("vm");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const storage = {};
const storageWrites = [];
const operationOrder = [];
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
        const keys = Object.keys(values);
        storageWrites.push(...keys);
        for (const key of keys) {
          if (key === "caldavAssistant.currentWorkId") {
            operationOrder.push(
              "storage:" + key + ":" + (values[key] === null ? "null" : "value")
            );
          } else {
            operationOrder.push("storage:" + key);
          }
        }
        Object.assign(storage, values);
      },
      async remove(keys) {
        const names = Array.isArray(keys) ? keys : [keys];
        for (const key of names) {
          delete storage[key];
          operationOrder.push("storage:remove:" + key);
        }
      },
    },
  },
};

const task = {
  id: "seed-task",
  calendarId: "tasks",
  calendarName: "Tasks",
  title: "Seed task",
  status: "NEEDS-ACTION",
  paused: false,
  percentComplete: 0,
  categories: ["Acceptance"],
};

let eventCounter = 0;
const events = new Map();
const faults = {
  corruptNextWorkReadback: false,
  failNextPausedWrite: false,
  failNextStopWrite: false,
  failNextCompleteWrite: false,
  failNextEventClose: false,
  throwAfterNextEventCreate: false,
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function resetTask() {
  task.status = "NEEDS-ACTION";
  task.paused = false;
  task.percentComplete = 0;
}

function resetAll() {
  resetTask();
  events.clear();
  eventCounter = 0;
  for (const key of Object.keys(storage)) delete storage[key];
  storageWrites.length = 0;
  operationOrder.length = 0;
  for (const key of Object.keys(faults)) faults[key] = false;
}

browser.ThunderbirdCalDAV = {
  async updateTask(calendarId, itemId, changes) {
    assert(calendarId === task.calendarId && itemId === task.id, "wrong task target");
    operationOrder.push("task:update:" + String(changes.status || ""));
    if (faults.failNextPausedWrite && changes.paused === true) {
      faults.failNextPausedWrite = false;
      throw new Error("simulated paused write failure");
    }
    if (faults.failNextStopWrite && changes.status === "NEEDS-ACTION") {
      faults.failNextStopWrite = false;
      throw new Error("simulated stop write failure");
    }
    if (faults.failNextCompleteWrite && changes.status === "COMPLETED") {
      faults.failNextCompleteWrite = false;
      throw new Error("simulated complete write failure");
    }
    if ("status" in changes) task.status = changes.status || "";
    if ("paused" in changes) task.paused = Boolean(changes.paused);
    if ("percentComplete" in changes) task.percentComplete = Number(changes.percentComplete);
    if (task.status === "COMPLETED") task.percentComplete = 100;
    return clone(task);
  },
  async getTask(calendarId, itemId) {
    assert(calendarId === task.calendarId && itemId === task.id, "wrong task readback target");
    operationOrder.push("task:read:" + String(task.status || ""));
    return clone(task);
  },
  async createEvent(calendarId, values) {
    operationOrder.push("event:create");
    const id = values.id || "work-" + (++eventCounter);
    const event = {
      id,
      calendarId,
      calendarName: "Work",
      title: values.title,
      start: {icalString: values.start.replace(/[-:]/g, "")},
      end: values.end ? {icalString: values.end.replace(/[-:]/g, "")} : null,
      taskUid: values.taskUid || "",
      workSession: Boolean(values.workSession),
      workOpen: Boolean(values.workOpen),
      status: values.status || "",
    };
    events.set(id, event);
    if (faults.throwAfterNextEventCreate) {
      faults.throwAfterNextEventCreate = false;
      throw new Error("simulated uncertain create response");
    }
    return clone(event);
  },
  async updateEvent(calendarId, itemId, changes) {
    const event = events.get(itemId);
    assert(event && event.calendarId === calendarId, "wrong event target");
    if (faults.failNextEventClose && changes.workOpen === false) {
      faults.failNextEventClose = false;
      throw new Error("simulated Work VEVENT close failure");
    }
    if ("end" in changes) {
      event.end = changes.end
        ? {icalString: String(changes.end).replace(/[-:]/g, "")}
        : null;
    }
    if ("workOpen" in changes) event.workOpen = Boolean(changes.workOpen);
    return clone(event);
  },
  async getEvent(calendarId, itemId) {
    const event = events.get(itemId);
    if (!event || event.calendarId !== calendarId) throw new Error("Calendar item not found");
    operationOrder.push("event:read");
    const result = clone(event);
    if (faults.corruptNextWorkReadback && result.workSession) {
      faults.corruptNextWorkReadback = false;
      result.taskUid = "";
    }
    return result;
  },
  async deleteEvent(calendarId, itemId) {
    const event = events.get(itemId);
    if (!event || event.calendarId !== calendarId) {
      throw new Error("Calendar item not found");
    }
    events.delete(itemId);
    return {ok: true, id: itemId};
  },
};

global.window = global;

for (const script of [
  "addon/core/storage.js",
  "addon/core/action-plan.js",
  "addon/core/executor.js",
]) {
  vm.runInThisContext(fs.readFileSync(script, "utf8"), {filename: script});
}

async function normalLifecycle() {
  assert(typeof AssistantExecutor.pause === "undefined", "Pause API still exposed");
  assert(typeof AssistantExecutor.resume === "undefined", "Resume API still exposed");
  assert(typeof AssistantExecutor.switchAway === "undefined", "Switch Away API still exposed");

  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "start failed");
  assert(receipt.logSaved === true, "start result was returned before persistent log success");
  const firstAuditWrite = storageWrites.findIndex(key => key.startsWith("caldavAssistant.audit."));
  const firstReceiptWrite = storageWrites.indexOf("caldavAssistant.lastReceipt");
  assert(
    firstAuditWrite >= 0 && firstReceiptWrite >= 0 && firstAuditWrite < firstReceiptWrite,
    "result cache was written before the persistent audit log"
  );
  assert(task.status === "IN-PROCESS", "start did not set task IN-PROCESS");
  assert(task.paused === false, "start did not normalize legacy pause marker");
  const taskWriteIndex = operationOrder.indexOf("task:update:IN-PROCESS");
  const taskReadIndex = operationOrder.indexOf("task:read:IN-PROCESS");
  const eventCreateIndex = operationOrder.indexOf("event:create");
  const eventReadIndex = operationOrder.indexOf("event:read");
  const currentIdWriteIndex = operationOrder.indexOf(
    "storage:caldavAssistant.currentWorkId:value"
  );
  assert(taskReadIndex > taskWriteIndex, "Start published effects before Task read-back");
  assert(eventCreateIndex > taskReadIndex, "Work event was created before Task read-back");
  assert(eventReadIndex > eventCreateIndex, "Work event was not verified by read-back");
  assert(currentIdWriteIndex > eventReadIndex, "currentWorkId was published too early");

  const startedWorkId = await AssistantStorage.getCurrentWorkId();
  assert(startedWorkId, "start did not publish currentWorkId");
  const firstWorkRef = await AssistantStorage.findOpenWorkSessionRef(clone(task));
  const firstWorkId = firstWorkRef?.id;
  assert(firstWorkRef?.source === "audit", "Start Work VEVENT ref did not derive from audit");
  assert(firstWorkId && events.get(firstWorkId)?.workOpen, "start did not persist open Work VEVENT");

  receipt = await AssistantExecutor.stop(clone(task));
  assert(receipt.success, "stop failed");
  assert(task.status === "NEEDS-ACTION", "stop did not restore pre-Start status");
  assert(task.paused === false, "stop resurrected paused lifecycle");
  assert(task.percentComplete === 0, "stop changed original progress");
  assert(await AssistantStorage.getCurrentWorkId() === null, "stop did not clear currentWorkId");
  assert(events.get(firstWorkId)?.end && !events.get(firstWorkId)?.workOpen, "stop did not close Work VEVENT");
  let timing = await AssistantStorage.deriveWorkTiming(clone(task));
  assert(timing.segmentStartedAtMs === null, "Stop timing left a live segment");

  receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "restart after Stop failed");
  const secondWorkRef = await AssistantStorage.findOpenWorkSessionRef(clone(task));
  const secondWorkId = secondWorkRef?.id;
  assert(secondWorkId && secondWorkId !== firstWorkId, "restart did not create a new Work VEVENT");

  receipt = await AssistantExecutor.complete(clone(task));
  assert(receipt.success, "complete failed");
  assert(task.status === "COMPLETED", "complete did not set COMPLETED");
  assert(task.percentComplete === 100, "complete did not set 100 percent");
  assert(await AssistantStorage.getCurrentWorkId() === null, "complete did not clear currentWorkId");
  assert(events.get(secondWorkId)?.end && !events.get(secondWorkId)?.workOpen, "complete did not close Work VEVENT");

  const audit = await AssistantStorage.listAudit();
  assert(
    audit.map(row => row.action).join(",") === "start,stop,start,complete",
    "new lifecycle audit sequence is incomplete"
  );
  assert(audit.every(row => row.details?.steps?.length), "audit records lost detailed receipts");

  const failure = await AssistantExecutor.stop(clone(task));
  assert(!failure.success, "invalid Stop should return a persistent failed receipt");
  assert(/already finished|not the current task/i.test(failure.error), "wrong Stop failure reason");
  const last = await AssistantStorage.getLastReceipt();
  assert(last?.id === failure.id, "failed Stop receipt was not persisted");
}

async function legacyRuntimeMigration() {
  resetAll();
  storage["caldavAssistant.runtime"] = {
    state: "paused",
    currentTask: {
      id: "seed-task",
      calendarId: "tasks",
      recurrenceId: "20261003T090000",
    },
    currentWorkEvent: {id: "legacy-work-event", calendarId: "work"},
    segmentStartedAtMs: null,
    accumulatedMs: 1234,
  };

  const currentWorkId = await AssistantStorage.getCurrentWorkId();
  const ref = AssistantStorage.parseWorkTaskId(currentWorkId);
  assert(ref?.calendarId === "tasks", "legacy migration lost calendar id");
  assert(ref?.id === "seed-task", "legacy migration lost task uid");
  assert(
    ref?.recurrenceId === "20261003T090000",
    "legacy migration lost recurrence identity"
  );
  assert(
    storage["caldavAssistant.runtime"]?.currentWorkEvent?.id === "legacy-work-event",
    "compat migration destroyed legacy runtime too early"
  );
  const legacyTask = {
    id: "seed-task",
    calendarId: "tasks",
    recurrenceId: "20261003T090000",
  };
  const legacyTiming = await AssistantStorage.deriveWorkTiming(legacyTask);
  assert(legacyTiming.source === "audit", "legacy timing was not migrated into immutable audit");
  assert(legacyTiming.accumulatedMs === 1234, "old session timing lost accumulated duration");
  const migrationRows = await AssistantStorage.listAudit();
  assert(
    migrationRows.some(row => row.action === "legacy-runtime-baseline"),
    "legacy currentWorkId migration did not persist an immutable timing baseline"
  );
  const legacyWorkEvent = await AssistantStorage.findOpenWorkSessionRef(legacyTask);
  assert(legacyWorkEvent?.source === "legacy-runtime", "old Work VEVENT ref lost fallback");
  assert(legacyWorkEvent?.id === "legacy-work-event", "old Work VEVENT id was not recovered");
  assert(legacyWorkEvent?.calendarId === "work", "old Work VEVENT calendar was not recovered");

  storage["caldavAssistant.currentWorkId"] = "corrupt";
  const recovered = await AssistantStorage.getCurrentWorkId();
  assert(
    recovered === currentWorkId,
    "corrupt currentWorkId did not recover from legacy runtime"
  );
}

async function legacyRuntimeStateIsNotWorkflowTruth() {
  resetAll();

  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "state-truth setup Start failed");

  storage["caldavAssistant.runtime"] = {
    state: "paused",
    currentTask: {
      id: task.id,
      calendarId: task.calendarId,
      recurrenceId: "",
    },
    currentWorkEvent: {id: "wrong-event", calendarId: "work"},
    accumulatedMs: 999999,
  };

  receipt = await AssistantExecutor.stop(clone(task));
  assert(
    receipt.success,
    "Stop trusted stale legacy runtime instead of currentWorkId + immutable Start history"
  );
  assert(task.status === "NEEDS-ACTION" && task.paused === false, "Stop restore facts wrong");
  assert(await AssistantStorage.getCurrentWorkId() === null, "Stop did not clear pointer");

  receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "state-truth restart failed");
  receipt = await AssistantExecutor.cancel(clone(task));
  assert(receipt.success, "state-truth cleanup Cancel failed");
}

async function startReadbackRollback() {
  resetAll();
  faults.corruptNextWorkReadback = true;
  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "Work VEVENT read-back failure incorrectly blocked Start");
  assert(task.status === "IN-PROCESS", "Start did not keep authoritative Task state");
  assert(task.paused === false, "Start incorrectly paused Task");
  assert(events.size === 0, "failed Work history read-back left an orphan VEVENT");
  assert(await AssistantStorage.getCurrentWorkId(), "Start did not publish currentWorkId");
  assert(
    receipt.steps.some(
      step =>
        step.component === "Work Session" &&
        step.operation === "optional history create failed" &&
        step.success === false
    ),
    "Start did not report optional Work history failure"
  );

  receipt = await AssistantExecutor.cancel(clone(task));
  assert(receipt.success, "Start history-failure cleanup Cancel failed");
}

async function uncertainCreateRollback() {
  resetAll();
  faults.throwAfterNextEventCreate = true;
  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "uncertain Work history create incorrectly blocked Start");
  assert(events.size === 0, "uncertain event create left an orphan VEVENT");
  assert(task.status === "IN-PROCESS", "uncertain Work history changed Task workflow");
  assert(await AssistantStorage.getCurrentWorkId(), "uncertain Work history lost currentWorkId");
  assert(
    receipt.steps.some(step => step.operation === "delete created VEVENT" && step.success),
    "known Work UID did not allow cleanup after uncertain create"
  );
  assert(
    receipt.steps.some(step => step.operation === "optional history create failed"),
    "uncertain create was not exposed as auxiliary history failure"
  );

  receipt = await AssistantExecutor.cancel(clone(task));
  assert(receipt.success, "uncertain Work history cleanup Cancel failed");
}

async function startWithoutWorkCalendar() {
  resetAll();

  let receipt = await AssistantExecutor.start(clone(task), null);
  assert(receipt.success, "missing Work Calendar incorrectly blocked Start");
  assert(task.status === "IN-PROCESS", "Start without Work Calendar lost Task state");
  assert(await AssistantStorage.getCurrentWorkId(), "Start without Work Calendar lost pointer");
  assert(events.size === 0, "Start without Work Calendar unexpectedly created VEVENT");
  assert(
    receipt.steps.some(
      step =>
        step.operation === "optional history create failed" &&
        /No writable Work calendar/i.test(step.details?.message || "")
    ),
    "missing Work Calendar was not recorded as optional history failure"
  );

  receipt = await AssistantExecutor.cancel(clone(task));
  assert(receipt.success, "Start without Work Calendar cleanup Cancel failed");
}

async function pauseDerivesWorkEventWithoutRuntimeRef() {
  resetAll();

  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "derived Work-event setup Start failed");

  assert(
    storage["caldavAssistant.runtime"] === undefined,
    "new Start unexpectedly created legacy runtime"
  );
  const derived = await AssistantStorage.findOpenWorkSessionRef(clone(task));
  const workId = derived?.id;
  assert(workId && events.has(workId), "setup did not create Work VEVENT");


  assert(derived?.source === "audit", "open Work VEVENT was not derived from audit");
  assert(derived?.id === workId, "audit derived the wrong Work VEVENT");

  receipt = await AssistantExecutor.pause(clone(task));
  assert(receipt.success, "Pause still depended on runtime.currentWorkEvent");
  assert(events.get(workId)?.end, "Pause did not close audit-derived Work VEVENT");
  assert(events.get(workId)?.workOpen === false, "Pause left audit-derived Work VEVENT open");

  receipt = await AssistantExecutor.switchAway(clone(task));
  assert(receipt.success, "derived Work-event cleanup Switch Away failed");
}

async function pauseCloseFailureDoesNotBlockWorkflow() {
  resetAll();

  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "close-failure setup Start failed");
  const workRef = await AssistantStorage.findOpenWorkSessionRef(clone(task));
  const workId = workRef?.id;
  assert(workId && events.get(workId)?.workOpen, "close-failure setup has no open Work VEVENT");

  faults.failNextEventClose = true;
  receipt = await AssistantExecutor.pause(clone(task));
  assert(receipt.success, "Work VEVENT close failure incorrectly blocked Pause");
  assert(task.status === "IN-PROCESS" && task.paused === true, "Pause VTODO state was not committed");
  assert(await AssistantStorage.getCurrentWorkId(), "Pause close failure lost currentWorkId");
  assert(events.get(workId)?.workOpen === true, "simulated close failure unexpectedly mutated VEVENT");
  assert(
    receipt.steps.some(step => step.operation === "optional history close failed"),
    "Pause did not expose auxiliary Work history close failure"
  );

  receipt = await AssistantExecutor.switchAway(clone(task));
  assert(receipt.success, "close-failure cleanup Switch Away failed");
}

async function pauseWriteRollback() {
  resetAll();
  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "setup Start failed");
  const workRef = await AssistantStorage.findOpenWorkSessionRef(clone(task));
  const workId = workRef?.id;
  assert(workId, "setup Start has no audit-derived Work VEVENT");

  faults.failNextPausedWrite = true;
  receipt = await AssistantExecutor.pause(clone(task));
  assert(!receipt.success, "simulated Pause write failure should fail");
  assert(task.status === "IN-PROCESS" && task.paused === false, "failed Pause changed Task state");
  assert(events.get(workId)?.workOpen === true, "failed Pause did not reopen Work VEVENT");
  assert(
    storage["caldavAssistant.runtime"] === undefined,
    "failed Pause wrote legacy runtime"
  );
  assert(await AssistantStorage.getCurrentWorkId(), "failed Pause lost currentWorkId");
}

async function resumeReadbackRollback() {
  resetAll();
  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "setup Start failed");
  receipt = await AssistantExecutor.pause(clone(task));
  assert(receipt.success, "setup Pause failed");
  const beforeEvents = new Set(events.keys());

  faults.corruptNextWorkReadback = true;
  receipt = await AssistantExecutor.resume(clone(task), "work");
  assert(receipt.success, "Work VEVENT read-back failure incorrectly blocked Resume");
  assert(task.status === "IN-PROCESS" && task.paused === false, "Resume did not commit VTODO state");
  assert(events.size === beforeEvents.size, "failed Resume history left an extra Work VEVENT");
  for (const id of beforeEvents) assert(events.has(id), "Resume history failure removed previous VEVENT");
  assert(await AssistantStorage.getCurrentWorkId(), "Resume history failure lost currentWorkId");
  assert(
    receipt.steps.some(step => step.operation === "optional history create failed"),
    "Resume did not expose auxiliary Work history failure"
  );

  receipt = await AssistantExecutor.cancel(clone(task));
  assert(receipt.success, "Resume history-failure cleanup Cancel failed");
}

async function switchAwayLifecycle() {
  resetAll();
  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "Switch-away setup Start failed");
  const workRef = await AssistantStorage.findOpenWorkSessionRef(clone(task));
  const workId = workRef?.id;
  assert(workId, "Switch-away setup has no Work VEVENT");

  receipt = await AssistantExecutor.switchAway(clone(task));
  assert(receipt.success, "Switch-away failed");
  assert(task.status === "NEEDS-ACTION", "Switch-away did not restore incomplete status");
  assert(task.paused === false, "Switch-away incorrectly left Task paused/resumable");
  assert(task.percentComplete === 0, "Switch-away changed original progress");
  assert(events.get(workId)?.end && !events.get(workId)?.workOpen, "Switch-away did not close Work VEVENT");
  assert(
    storage["caldavAssistant.runtime"] === undefined,
    "Switch-away wrote legacy runtime"
  );
  assert(await AssistantStorage.getCurrentWorkId() === null, "Switch-away did not clear currentWorkId");

  receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "Task could not be started again after switch-away");
  assert(task.status === "IN-PROCESS" && task.paused === false, "Restart after switch-away is wrong");
  assert(
    await AssistantStorage.getCurrentWorkId() === AssistantStorage.makeWorkTaskId(task),
    "Restart after switch-away did not become current"
  );

  receipt = await AssistantExecutor.cancel(clone(task));
  assert(receipt.success, "Switch-away cleanup Cancel failed");
}

async function switchAwayPausedLifecycle() {
  resetAll();
  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "Paused switch-away setup Start failed");
  receipt = await AssistantExecutor.pause(clone(task));
  assert(receipt.success, "Paused switch-away setup Pause failed");

  receipt = await AssistantExecutor.switchAway(clone(task));
  assert(receipt.success, "Switch-away from paused state failed");
  assert(task.status === "NEEDS-ACTION", "Paused switch-away did not restore incomplete status");
  assert(task.paused === false, "Paused switch-away left resumable paused state");
  assert(
    storage["caldavAssistant.runtime"] === undefined,
    "Paused switch-away wrote legacy runtime"
  );
  assert(await AssistantStorage.getCurrentWorkId() === null, "Paused switch-away did not clear currentWorkId");
}

async function switchAwayRestoresFromAuditWithoutRuntimeSnapshot() {
  resetAll();
  task.status = "NEEDS-ACTION";
  task.paused = false;
  task.percentComplete = 37;

  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "Audit restore setup Start failed");

  assert(
    storage["caldavAssistant.runtime"] === undefined,
    "new Start should not create taskBeforeStart runtime state"
  );

  receipt = await AssistantExecutor.switchAway(clone(task));
  assert(receipt.success, "Switch-away could not restore from audit history");
  assert(task.status === "NEEDS-ACTION", "Audit restore lost original status");
  assert(task.paused === false, "Audit restore invented paused state");
  assert(task.percentComplete === 37, "Audit restore lost original progress");
}

async function switchAwayFallsBackToLegacyRuntimeSnapshot() {
  resetAll();
  task.status = "IN-PROCESS";
  task.paused = false;
  task.percentComplete = 41;

  await AssistantStorage.setCurrentWorkId(AssistantStorage.makeWorkTaskId(task));
  storage["caldavAssistant.runtime"] = {
    state: "working",
    currentTask: {
      id: task.id,
      calendarId: task.calendarId,
      recurrenceId: "",
    },
    currentWorkEvent: null,
    segmentStartedAtMs: Date.now(),
    accumulatedMs: 0,
    taskBeforeStart: {
      status: "NEEDS-ACTION",
      paused: false,
      percentComplete: 41,
    },
  };

  const receipt = await AssistantExecutor.switchAway(clone(task));
  assert(receipt.success, "Switch-away lost legacy runtime fallback");
  assert(task.status === "NEEDS-ACTION", "Legacy fallback lost original status");
  assert(task.paused === false, "Legacy fallback invented paused state");
  assert(task.percentComplete === 41, "Legacy fallback lost original progress");
  assert(await AssistantStorage.getCurrentWorkId() === null, "Legacy fallback did not clear pointer");
  assert(
    storage["caldavAssistant.runtime"] === undefined,
    "completed legacy migration left stale runtime data behind"
  );
}

async function switchAwayRestoresExactPreStartProgress() {
  resetAll();
  task.status = "NEEDS-ACTION";
  task.paused = false;
  task.percentComplete = 35;

  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "Progress restore setup Start failed");
  assert(task.status === "IN-PROCESS" && task.percentComplete === 35, "Start lost existing progress");

  receipt = await AssistantExecutor.switchAway(clone(task));
  assert(receipt.success, "Progress restore switch-away failed");
  assert(task.status === "NEEDS-ACTION", "Switch-away did not restore original status");
  assert(task.paused === false, "Switch-away invented paused state");
  assert(task.percentComplete === 35, "Switch-away did not restore original progress");
}

async function stopDerivesWorkEventWithoutRuntimeRef() {
  resetAll();

  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "Stop Work-event setup Start failed");
  assert(storage["caldavAssistant.runtime"] === undefined, "new Start created legacy runtime");

  const derived = await AssistantStorage.findOpenWorkSessionRef(clone(task));
  const workId = derived?.id;
  assert(derived?.source === "audit", "open Work VEVENT was not derived from audit");
  assert(workId && events.has(workId), "setup did not create Work VEVENT");

  receipt = await AssistantExecutor.stop(clone(task));
  assert(receipt.success, "Stop depended on runtime.currentWorkEvent");
  assert(events.get(workId)?.end, "Stop did not close audit-derived Work VEVENT");
  assert(events.get(workId)?.workOpen === false, "Stop left audit-derived Work VEVENT open");
}

async function stopCloseFailureDoesNotBlockWorkflow() {
  resetAll();

  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "close-failure setup Start failed");
  const workRef = await AssistantStorage.findOpenWorkSessionRef(clone(task));
  const workId = workRef?.id;
  assert(workId && events.get(workId)?.workOpen, "close-failure setup has no open Work VEVENT");

  faults.failNextEventClose = true;
  receipt = await AssistantExecutor.stop(clone(task));
  assert(receipt.success, "Work VEVENT close failure incorrectly blocked Stop");
  assert(task.status === "NEEDS-ACTION" && task.paused === false, "Stop VTODO restore was not committed");
  assert(await AssistantStorage.getCurrentWorkId() === null, "Stop close failure retained currentWorkId");
  assert(events.get(workId)?.workOpen === true, "simulated close failure unexpectedly mutated VEVENT");
  assert(
    receipt.steps.some(step => step.operation === "optional history close failed"),
    "Stop did not expose auxiliary Work history close failure"
  );
}

async function stopWriteRollback() {
  resetAll();

  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "Stop rollback setup Start failed");
  const workRef = await AssistantStorage.findOpenWorkSessionRef(clone(task));
  const workId = workRef?.id;
  assert(workId && events.get(workId)?.workOpen, "Stop rollback setup has no open Work VEVENT");

  faults.failNextStopWrite = true;
  receipt = await AssistantExecutor.stop(clone(task));
  assert(!receipt.success, "simulated Stop Task write failure should fail");
  assert(task.status === "IN-PROCESS" && task.paused === false, "failed Stop changed Task state");
  assert(await AssistantStorage.getCurrentWorkId(), "failed Stop lost currentWorkId");
  assert(events.get(workId)?.workOpen === true, "failed Stop did not reopen Work VEVENT");
}

async function stopRestoresExactPreStartProgress() {
  resetAll();
  task.status = "NEEDS-ACTION";
  task.paused = false;
  task.percentComplete = 35;

  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "progress restore setup Start failed");
  assert(task.status === "IN-PROCESS" && task.percentComplete === 35, "Start lost existing progress");

  receipt = await AssistantExecutor.stop(clone(task));
  assert(receipt.success, "progress restore Stop failed");
  assert(task.status === "NEEDS-ACTION", "Stop did not restore original status");
  assert(task.paused === false, "Stop invented paused state");
  assert(task.percentComplete === 35, "Stop did not restore original progress");
}

async function stopFallsBackToLegacyRuntimeSnapshot() {
  resetAll();
  task.status = "IN-PROCESS";
  task.paused = true;
  task.percentComplete = 41;

  await AssistantStorage.setCurrentWorkId(AssistantStorage.makeWorkTaskId(task));
  storage["caldavAssistant.runtime"] = {
    state: "paused",
    currentTask: {
      id: task.id,
      calendarId: task.calendarId,
      recurrenceId: "",
    },
    currentWorkEvent: null,
    segmentStartedAtMs: null,
    accumulatedMs: 0,
    taskBeforeStart: {
      status: "NEEDS-ACTION",
      paused: true,
      percentComplete: 41,
    },
  };

  const receipt = await AssistantExecutor.stop(clone(task));
  assert(receipt.success, "Stop lost legacy runtime fallback");
  assert(task.status === "NEEDS-ACTION", "legacy fallback lost original status");
  assert(task.paused === false, "Stop resurrected legacy paused lifecycle");
  assert(task.percentComplete === 41, "legacy fallback lost original progress");
  assert(await AssistantStorage.getCurrentWorkId() === null, "legacy fallback did not clear pointer");
  assert(storage["caldavAssistant.runtime"] === undefined, "completed migration left stale runtime");
}

async function cancelLifecycle() {
  resetAll();
  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "Cancel setup Start failed");
  const workRef = await AssistantStorage.findOpenWorkSessionRef(clone(task));
  const workId = workRef?.id;
  assert(workId, "Cancel setup has no Work VEVENT");

  receipt = await AssistantExecutor.cancel(clone(task));
  assert(receipt.success, "Cancel failed");
  assert(task.status === "CANCELLED", "Cancel did not set CANCELLED");
  assert(task.paused === false, "Cancel left Task paused");
  assert(events.get(workId)?.end && !events.get(workId)?.workOpen, "Cancel did not close Work VEVENT");
  assert(
    storage["caldavAssistant.runtime"] === undefined,
    "Cancel wrote legacy runtime"
  );
  assert(await AssistantStorage.getCurrentWorkId() === null, "Cancel did not clear currentWorkId");
  assert(
    receipt.steps.some(step => step.component === "WordPress" && step.operation === "not invoked"),
    "Cancel receipt must explicitly say WordPress was not invoked"
  );
}

async function completeWriteRollback() {
  resetAll();
  let receipt = await AssistantExecutor.start(clone(task), "work");
  assert(receipt.success, "setup Start failed");
  const workRef = await AssistantStorage.findOpenWorkSessionRef(clone(task));
  const workId = workRef?.id;
  assert(workId, "Complete rollback setup has no Work VEVENT");

  faults.failNextCompleteWrite = true;
  receipt = await AssistantExecutor.complete(clone(task));
  assert(!receipt.success, "simulated Complete write failure should fail");
  assert(task.status === "IN-PROCESS" && task.percentComplete === 0, "failed Complete changed Task");
  assert(events.get(workId)?.workOpen === true, "failed Complete did not reopen Work VEVENT");
  assert(
    storage["caldavAssistant.runtime"] === undefined,
    "failed Complete wrote legacy runtime"
  );
  assert(await AssistantStorage.getCurrentWorkId(), "failed Complete lost currentWorkId");
}

(async () => {
  resetAll();
  await normalLifecycle();
  await legacyRuntimeMigration();
  await legacyRuntimeStateIsNotWorkflowTruth();
  await startReadbackRollback();
  await uncertainCreateRollback();
  await startWithoutWorkCalendar();
  await stopDerivesWorkEventWithoutRuntimeRef();
  await stopCloseFailureDoesNotBlockWorkflow();
  await stopWriteRollback();
  await stopRestoresExactPreStartProgress();
  await stopFallsBackToLegacyRuntimeSnapshot();
  await cancelLifecycle();
  await completeWriteRollback();
  assert(
    !storageWrites.includes("caldavAssistant.runtime"),
    "new workflow wrote the legacy runtime key"
  );
  console.log("workflow-harness: PASS");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
