"use strict";
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const source = fs.readFileSync("addon/api/PostPreview/child.js", "utf8")
  .replace("export class CalDAVPostPreviewChild", "class CalDAVPostPreviewChild")
  + "\nthis.Actor = CalDAVPostPreviewChild;";
const sandbox = {JSWindowActorChild: class {}};
vm.runInNewContext(source, sandbox);
const actor = new sandbox.Actor();
const calls = [];
const last = {scrollIntoView(options) {calls.push(options);}};
actor.document = {
  documentURI: "https://andrew.local/2026/10/17/post/",
  querySelector(selector) {
    assert(selector.includes(".entry-content"));
    return {lastElementChild: last};
  },
};
actor.contentWindow = {
  scrollY: 0,
  requestAnimationFrame(callback) {callback();},
};
(async () => {
  const receipt = await actor.receiveMessage({name: "scrollToPostEnd"});
  assert.equal(receipt.target, "post-content-end");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].block, "end");
  actor.document.querySelector = () => null;
  await assert.rejects(actor.receiveMessage({name: "scrollToPostEnd"}), /Post content was not found/);
  assert.equal(calls.length, 1, "Missing Post content must not fall back to site bottom");
  console.log("post-preview-actor-harness: PASS (Post content end, no site footer fallback)");
})().catch(error => {console.error(error); process.exit(1);});
