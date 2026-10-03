"use strict";

const fs = require("fs");
const path = require("path");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const manifest = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "addon", "manifest.json"), "utf8")
);

assert(
  manifest.browser_specific_settings?.gecko?.id ===
    "ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net",
  "clean-room add-on must retain the existing extension ID for profile migration"
);
assert(manifest.version === "0.4.0", "unexpected clean-room version");
assert(manifest.default_locale === "en", "default locale must be English");
assert(manifest.name === "__MSG_extensionName__", "manifest name must be localized");
assert(
  manifest.description === "__MSG_extensionDescription__",
  "manifest description must be localized"
);
assert(
  Array.isArray(manifest.background?.scripts) &&
    manifest.background.scripts[0] === "generated/core.js" &&
    manifest.background.scripts[1] === "background.js",
  "typed core must load before startup shell"
);
assert(
  Object.keys(manifest.experiment_apis || {}).join(",") === "NativeTasks",
  "manifest exposed unexpected legacy Experiment APIs"
);

const text = JSON.stringify(manifest);
for (const forbidden of ["TaskFix", "WORK-SESSION", "WORK-OPEN"]) {
  assert(!text.includes(forbidden), "manifest contains old framework marker: " + forbidden);
}

console.log("clean-room manifest: PASS");
