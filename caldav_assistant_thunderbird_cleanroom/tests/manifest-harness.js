"use strict";

const fs = require("fs");
const path = require("path");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const root = path.resolve(__dirname, "..");
const manifest = JSON.parse(
  fs.readFileSync(path.join(root, "addon/manifest.json"), "utf8")
);
const background = fs.readFileSync(
  path.join(root, "addon/background.js"),
  "utf8"
);

assert(
  manifest.browser_specific_settings?.gecko?.id ===
    "ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net",
  "Extension id changed; existing browser.storage.local data would be lost"
);
assert(
  JSON.stringify(Object.keys(manifest.experiment_apis || {})) ===
    JSON.stringify(["ThunderbirdTasks"]),
  "Unexpected Experiment API leaked into clean-room manifest"
);
assert(
  JSON.stringify(manifest.background?.scripts || []) ===
    JSON.stringify(["background.js"]),
  "Background must stay a single thin loader"
);

for (const forbidden of [
  "WorkEvent",
  "WORK-SESSION",
  "WORK-OPEN",
  "pause",
  "resume",
  "switch-away",
]) {
  assert(
    !JSON.stringify(manifest).includes(forbidden) &&
      !background.includes(forbidden),
    "Legacy workflow concept leaked into packaged startup: " + forbidden
  );
}

assert(
  background.includes('browser.runtime.getURL("dist/startup.js")'),
  "Background does not load the compiled clean-room startup module"
);

console.log("manifest-harness: PASS");
