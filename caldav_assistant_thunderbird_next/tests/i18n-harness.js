"use strict";

const fs = require("fs");
const path = require("path");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function readLocale(locale) {
  return JSON.parse(
    fs.readFileSync(
      path.join(__dirname, "..", "addon", "_locales", locale, "messages.json"),
      "utf8"
    )
  );
}

const en = readLocale("en");
const zh = readLocale("zh_CN");

const enKeys = Object.keys(en).sort();
const zhKeys = Object.keys(zh).sort();

assert(
  JSON.stringify(enKeys) === JSON.stringify(zhKeys),
  "English and Simplified Chinese locale keys differ"
);

for (const [locale, messages] of [["en", en], ["zh_CN", zh]]) {
  for (const [key, entry] of Object.entries(messages)) {
    assert(
      entry && typeof entry.message === "string" && entry.message.trim(),
      `${locale} message ${key} is empty`
    );
  }
}

for (const required of [
  "extensionName",
  "extensionDescription",
  "taskPickerTitle",
  "taskPageTitle",
  "todayTitle",
  "logsTitle",
  "settingsTitle",
  "toolsTitle",
  "wordpressTitle",
  "actionStart",
  "actionStop",
  "actionComplete",
  "actionCancel",
  "taskWorkLogMalformed",
  "currentPointerStale",
  "anotherTaskActive",
  "wordpressApplicationPassword",
  "wordpressQueued",
]) {
  assert(en[required], "missing required locale key: " + required);
}

const secretWords = JSON.stringify({en, zh});
assert(!secretWords.includes("SECRET-MUST-NOT-LEAK"), "locale resource contains test secret");

console.log("clean-room i18n: PASS");
