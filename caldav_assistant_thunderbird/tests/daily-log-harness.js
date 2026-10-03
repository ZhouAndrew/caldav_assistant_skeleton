"use strict";

const fs = require("fs");
const vm = require("vm");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const outbox = [
  {
    id: "legacy-1",
    attempts: 1,
    payload: {
      content: "09:00–09:30 Legacy queued entry",
      startIso: "2026-10-03T09:00:00.000Z",
      marker: "legacy-marker-1",
    },
  },
  {
    id: "legacy-2",
    attempts: 2,
    payload: {
      content: "10:00–10:10 Legacy queued entry 2",
      startIso: "2026-10-03T10:00:00.000Z",
      marker: "legacy-marker-2",
    },
  },
];

global.AssistantStorage = {
  async listWordPressOutbox() {
    return outbox.map(item => ({...item, payload: {...item.payload}}));
  },
  async updateWordPressOutbox(id, patch) {
    const item = outbox.find(row => row.id === id);
    if (!item) return null;
    Object.assign(item, patch);
    return item;
  },
  async removeWordPressOutbox(id) {
    const index = outbox.findIndex(row => row.id === id);
    if (index < 0) return false;
    outbox.splice(index, 1);
    return true;
  },
};

const calls = [];
let failMarker = "legacy-marker-2";
global.AssistantWordPress = {
  async createLog(payload) {
    calls.push({...payload});
    if (payload.marker === failMarker) {
      return {success: false, summary: "simulated WordPress failure"};
    }
    return {success: true, post: {id: 123}};
  },
};

global.window = global;
vm.runInThisContext(
  fs.readFileSync("addon/core/daily-log.js", "utf8"),
  {filename: "addon/core/daily-log.js"}
);

(async () => {
  assert(
    typeof AssistantWordPressOutbox.flushOutbox === "function",
    "WordPress Outbox retry service is missing"
  );
  assert(
    typeof AssistantWordPressOutbox.recordClosedWorkSession === "undefined",
    "Work Session Event lifecycle leaked back into Outbox service"
  );

  let result = await AssistantWordPressOutbox.flushOutbox();
  assert(result.processed === 2, "first retry did not inspect both legacy items");
  assert(result.sent === 1 && result.failed === 1, "first retry counts are wrong");
  assert(outbox.length === 1 && outbox[0].id === "legacy-2", "failed pending entry was lost");
  assert(outbox[0].attempts === 3, "failed entry attempt count was not updated");
  assert(calls[0].marker === "legacy-marker-1", "legacy idempotency marker changed");

  failMarker = "";
  result = await AssistantWordPressOutbox.flushOutbox();
  assert(result.sent === 1 && result.failed === 0, "second retry did not succeed");
  assert(outbox.length === 0, "successful legacy Outbox entry was not removed");
  assert(
    calls.some(call => call.marker === "legacy-marker-2"),
    "second legacy marker was not preserved"
  );

  console.log("daily-log-harness: PASS");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
