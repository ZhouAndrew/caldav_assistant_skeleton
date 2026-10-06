"use strict";
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const nodes = new Map();
for (const id of ["quick-capture", "capture-result", "open-post", "post-preview", "preview-status"]) {
  nodes.set(id, {hidden: true, textContent: "", listeners: {}, addEventListener(name, fn) {this.listeners[name] = fn;}});
}
const requests = [];
let outcome = {success: true, post: {link: "http://example.test/today?view=full#end"}};
let release;
let scrollCalls = [];
const context = {
  document: {getElementById: id => nodes.get(id)}, URL, Date,
  AssistantWordPress: {async createLog(payload) {
    requests.push(payload);
    if (release === null) await new Promise(resolve => {release = resolve;});
    return outcome;
  }},
  browser: {tabs: {getCurrent: async () => ({id: 7})},
    PostPreview: {scrollToBottom: async (...args) => {scrollCalls.push(args);}}},
};
vm.runInNewContext(fs.readFileSync("addon/quick-capture.js", "utf8"), context);
const capture = nodes.get("quick-capture");
const preview = nodes.get("post-preview");
const flush = () => new Promise(resolve => setImmediate(resolve));
function paste(content, files = [], items = []) {
  let prevented = false;
  capture.listeners.paste({clipboardData: {files, items, getData: type => type === "text/plain" ? content : ""},
    preventDefault() {prevented = true;}});
  return prevented;
}
function drop(files) {
  let prevented = false;
  capture.listeners.drop({dataTransfer: {files}, preventDefault() {prevented = true;}});
  return prevented;
}
(async () => {
  assert.deepEqual(Object.keys(capture.listeners).sort(), ["dragover", "drop", "paste"]);
  assert.deepEqual(Object.keys(preview.listeners), ["load"]);
  assert([...nodes].filter(([id]) => id !== "quick-capture")
    .every(([, node]) => !node.listeners.paste && !node.listeners.drop && !node.listeners.dragover));
  assert(!paste("  "));
  assert(paste("first\nsecond")); await flush();
  assert.equal(requests[0].content, "first\nsecond");
  assert.equal(nodes.get("open-post").href, outcome.post.link);
  const refreshed = new URL(preview.src);
  assert.equal(refreshed.searchParams.get("view"), "full");
  assert(refreshed.searchParams.has("refresh"));
  assert.equal(refreshed.hash, "#end");
  await preview.listeners.load();
  assert.deepEqual(scrollCalls, [[7, preview.src]]);
  const image = {name: "clipboard.png", type: "image/png"};
  assert(paste("", [], [{kind: "file", getAsFile: () => image}])); await flush();
  assert.equal(requests[1].files[0], image);
  const file = {name: "note.txt"};
  release = null;
  assert(drop([file, image]));
  assert(paste("queued independently")); await flush();
  assert.equal(requests.length, 3);
  assert.equal(requests[2].files.length, 2);
  release(); await flush(); await flush();
  assert.equal(requests.length, 4);
  const before = preview.src;
  outcome = {success: false, queued: true, summary: "WordPress offline"};
  paste("retained by existing service"); await flush();
  assert(nodes.get("capture-result").textContent.includes("Outbox"));
  assert.equal(preview.src, before);
  context.AssistantWordPress.createLog = async () => {throw new Error("storage unavailable");};
  paste("failure"); await flush();
  assert(nodes.get("capture-result").textContent.includes("storage unavailable"));
  console.log("quick-capture-harness: PASS (scoped input, transfer files, serialization, existing append, URL, preview, isolated failures)");
})().catch(error => {console.error(error); process.exit(1);});
