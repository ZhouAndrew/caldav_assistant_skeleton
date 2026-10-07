"use strict";
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const nodes = new Map(["post-preview", "preview-status", "open-post", "refresh-post"].map(id => [id,
  {hidden: true, textContent: "", listeners: {}, addEventListener(name, fn) {this.listeners[name] = fn;}}]));
let post = {link: "http://example.test/today?view=full#end"};
let reads = 0;
const scrolls = [];
const listeners = {};
const context = {
  document: {getElementById(id) {assert(nodes.has(id), "preview must not read Quick Capture elements"); return nodes.get(id);}},
  window: {addEventListener: (name, fn) => {listeners[name] = fn;}}, URL, Date,
  AssistantWordPress: {readDailyLogPost: async () => {reads++; return post;}},
  browser: {tabs: {getCurrent: async () => ({id: 1})}, PostPreview: {scrollToBottom: async (...args) => {scrolls.push(args);}}},
};
vm.runInNewContext(fs.readFileSync("addon/post-preview.js", "utf8"), context);
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  await flush();
  assert.equal(reads, 1);
  const preview = nodes.get("post-preview");
  assert(!preview.hidden);
  assert.equal(nodes.get("open-post").href, post.link);
  assert(new URL(preview.src).searchParams.has("refresh"));
  assert.equal(new URL(preview.src).searchParams.get("view"), "full");
  await preview.listeners.load();
  assert.deepEqual(scrolls, [[1, preview.src]]);
  assert.equal(nodes.get("preview-status").textContent, "");
  context.browser.PostPreview.scrollToBottom = async () => {throw new Error("找不到文章正文");};
  await preview.listeners.load();
  assert(nodes.get("preview-status").textContent.includes("找不到文章正文"));
  await nodes.get("refresh-post").listeners.click();
  assert.equal(reads, 2);
  await listeners["assistant-wordpress-appended"]();
  assert.equal(reads, 3);
  post = null;
  await nodes.get("refresh-post").listeners.click();
  assert(preview.hidden);
  assert.equal(nodes.get("preview-status").textContent, "今天尚无日志 Post。");
  context.AssistantWordPress.readDailyLogPost = async () => {throw new Error("offline");};
  await nodes.get("refresh-post").listeners.click();
  assert(nodes.get("preview-status").textContent.includes("offline"));
  assert.deepEqual(Object.keys(preview.listeners), ["load"]);
  console.log("post-preview-harness: PASS (independent initialization/read, no capture dependency, refresh, empty and failure)");
})().catch(error => {console.error(error); process.exit(1);});
