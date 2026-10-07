"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const context = {JSWindowActorChild: class {}};
vm.runInNewContext(fs.readFileSync("addon/api/PostPreview/child.js", "utf8")
  .replace("export class CalDAVPostPreviewChild", "this.Actor = class CalDAVPostPreviewChild"), context);
async function run(selector, bottom, initialY, viewport) {
  const actor = new context.Actor();
  let calls = 0;
  actor.contentWindow = {scrollY: initialY, innerHeight: viewport,
    requestAnimationFrame: fn => fn(),
    scrollTo(x, y) {assert.equal(x, 0); this.scrollY = y; calls++;}};
  actor.document = {documentURI: "http://example.test/post", querySelector(query) {
    return selector && query.includes(selector) ? {getBoundingClientRect: () => ({bottom: bottom - initialY})} : null;
  }, documentElement: {scrollHeight: 12000}, body: {scrollHeight: 12000}};
  const result = await actor.receiveMessage({name: "scrollToBottom"});
  assert.equal(result.articleBottom, bottom);
  assert.equal(result.scrollY, Math.max(0, bottom - viewport));
  assert.equal(calls, 1);
}
(async () => {
  await run("article .entry-content", 2400, 600, 500);
  await run("article .wp-block-post-content", 2400, 0, 500);
  await run("main .wp-block-post-content", 2400, 100, 500);
  await run(".entry-content", 240, 0, 500);
  await assert.rejects(run(null, 2400, 0, 500), /找不到文章正文/);
  const actor = new context.Actor();
  assert.equal(await actor.receiveMessage({name: "unrelated"}), null);
  console.log("post-preview-actor-harness: PASS (classic/block themes, footer excluded, short body, missing body refusal)");
})().catch(error => {console.error(error); process.exit(1);});
