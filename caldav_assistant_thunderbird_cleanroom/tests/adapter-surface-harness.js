"use strict";

const fs = require("fs");
const path = require("path");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const root = path.resolve(__dirname, "..");
const impl = fs.readFileSync(
  path.join(root, "addon/api/ThunderbirdTasks/implementation.js"),
  "utf8"
);
const schema = JSON.parse(
  fs.readFileSync(
    path.join(root, "addon/api/ThunderbirdTasks/schema.json"),
    "utf8"
  )
);

const names = schema[0].functions.map(item => item.name).sort();
assert(
  JSON.stringify(names) ===
    JSON.stringify(["getTask", "listCalendars", "listTasks", "updateTask"]),
  "ThunderbirdTasks API surface changed unexpectedly"
);

assert(
  impl.includes("modifyItem(newItem, oldItem)"),
  "VTODO updates must use Thunderbird revision checking"
);
assert(
  !impl.includes("modifyItem(newItem, null)"),
  "Adapter must not disable Thunderbird revision checking"
);

for (const forbidden of [
  "browser.storage",
  "currentWorkId",
  "WorkEvent",
  "workEvent",
  "WORK-SESSION",
  "WORK-OPEN",
  "WordPress",
  "createEvent",
  "updateEvent",
]) {
  assert(
    !impl.includes(forbidden),
    "VTODO adapter leaked unrelated concern: " + forbidden
  );
}

console.log("adapter-surface-harness: PASS");
