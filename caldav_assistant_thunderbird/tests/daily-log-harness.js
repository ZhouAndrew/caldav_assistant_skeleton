"use strict";

const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};
const fs = require("fs");
const vm = require("vm");

global.window = global;

const outbox = [];
const calls = [];
let failWrites = false;
let enabled = true;

function localDateKey(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  return (
    String(date.getFullYear()).padStart(4, "0") + "-" +
    String(date.getMonth() + 1).padStart(2, "0") + "-" +
    String(date.getDate()).padStart(2, "0")
  );
}

global.AssistantStorage = {
  localDateKey,
  async enqueueWordPressOutbox(entry) {
    const item = {
      id: "outbox-" + (outbox.length + 1),
      attempts: Number(entry.attempts || 0),
      lastError: entry.lastError || "",
      payload: entry.payload,
    };
    outbox.push(item);
    return item;
  },
  async listWordPressOutbox() {
    return outbox.map(item => ({...item}));
  },
  async updateWordPressOutbox(id, patch) {
    const item = outbox.find(row => row.id === id);
    Object.assign(item, patch || {});
    return item;
  },
  async removeWordPressOutbox(id) {
    const index = outbox.findIndex(row => row.id === id);
    if (index >= 0) outbox.splice(index, 1);
    return index >= 0;
  },
};

global.AssistantWordPress = {
  async getConfig() {
    return {dailyWorkLogEnabled: enabled};
  },
  async createLog(options) {
    calls.push({
      content: options.content,
      date: options.date,
      prefixTime: options.prefixTime,
      marker: options.marker,
    });
    if (failWrites) {
      return {success: false, summary: "simulated WordPress offline"};
    }
    return {
      success: true,
      deduplicated: false,
      post: {
        id: 123,
        title:
          options.date.getDate() === 2
            ? "October 2 Friday 2026"
            : "October 3 Saturday 2026",
      },
    };
  },
};

vm.runInThisContext(
  fs.readFileSync("addon/core/daily-log.js", "utf8"),
  {filename: "addon/core/daily-log.js"}
);

(async () => {
  const receipt = {steps: []};
  const task = {id: "task-anki", title: "Anki"};

  let result = await AssistantDailyLog.recordClosedWorkSession(
    task,
    {
      id: "work-one",
      taskUid: "task-anki",
      start: {icalString: "20261002T123054"},
      end: {icalString: "20261002T123157"},
    },
    receipt
  );
  assert(result.success, "normal Work Session did not reach WordPress");
  assert(calls.length === 1, "normal Work Session wrote more than once");
  assert(calls[0].content === "12:30–12:31 Anki", "work range text is wrong");
  assert(calls[0].prefixTime === false, "work range received an extra clock prefix");
  assert(
    calls[0].marker.includes("work-one") && calls[0].marker.includes("2026-10-02"),
    "work marker is not stable by Work UID/date"
  );
  assert(
    receipt.steps.some(step =>
      step.component === "WordPress" &&
      step.operation === "append daily work log" &&
      step.details.postId === 123
    ),
    "workflow receipt did not expose verified WordPress target"
  );

  calls.length = 0;
  result = await AssistantDailyLog.recordClosedWorkSession(
    task,
    {
      id: "work-midnight",
      taskUid: "task-anki",
      start: {icalString: "20261002T235900"},
      end: {icalString: "20261003T000100"},
    },
    {steps: []}
  );
  assert(result.success, "midnight Work Session failed");
  assert(calls.length === 2, "midnight Work Session was not split by date");
  assert(localDateKey(calls[0].date) === "2026-10-02", "first split date is wrong");
  assert(localDateKey(calls[1].date) === "2026-10-03", "second split date is wrong");
  assert(calls[0].marker !== calls[1].marker, "split entries reused one marker");

  calls.length = 0;
  outbox.length = 0;
  failWrites = true;
  result = await AssistantDailyLog.recordClosedWorkSession(
    task,
    {
      id: "work-offline",
      taskUid: "task-anki",
      start: {icalString: "20261002T130000"},
      end: {icalString: "20261002T131000"},
    },
    {steps: []}
  );
  assert(!result.success && result.queued, "offline WordPress was not queued");
  assert(outbox.length === 1, "offline WordPress did not create one Outbox item");

  const queuedMarker = outbox[0].payload.marker;
  failWrites = false;
  const flushed = await AssistantDailyLog.flushOutbox();
  assert(flushed.sent === 1 && flushed.failed === 0, "Outbox retry did not succeed");
  assert(outbox.length === 0, "successful Outbox item was not removed");
  assert(
    calls[calls.length - 1].marker === queuedMarker,
    "Outbox retry changed the idempotency marker"
  );

  enabled = false;
  calls.length = 0;
  result = await AssistantDailyLog.recordClosedWorkSession(
    task,
    {
      id: "work-disabled",
      start: {icalString: "20261002T140000"},
      end: {icalString: "20261002T141000"},
    },
    {steps: []}
  );
  assert(result.skipped, "disabled daily logging did not skip");
  assert(calls.length === 0, "disabled daily logging still wrote WordPress");

  console.log("daily-log-harness: PASS");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
