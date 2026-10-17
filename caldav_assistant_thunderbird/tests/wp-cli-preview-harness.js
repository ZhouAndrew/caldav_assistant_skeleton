"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const commands = [];
const config = {wordpress: {transport: "wp-cli", wordpressPath: "/var/www/html/wordpress", wpCliCommand: "wp"}};
const sandbox = {
  URL, Date, Blob,
  AssistantStorage: {
    getSettings: async () => config,
    localDateKey: () => "2026-10-17",
  },
  browser: {
    ThunderbirdCalDAV: {
      runWpCli: async ({args}) => {
        commands.push(args);
        if (args[0] === "post" && args[1] === "list") {
          return {exitCode: 0, stdout: JSON.stringify([
            {ID: 33, post_title: "October 17 Saturday 2026", post_status: "publish", guid: "https://andrew.local/"}
          ])};
        }
        if (args[0] === "post" && args[1] === "url" && args[2] === "33") {
          return {exitCode: 0, stdout: "https://andrew.local/2026/10/17/october-17-saturday-2026/\n"};
        }
        throw new Error("Unexpected WP-CLI command: " + args.join(" "));
      },
    },
  },
};
sandbox.globalThis = sandbox;
vm.runInNewContext(fs.readFileSync("addon/core/wordpress.js", "utf8"), sandbox);
(async () => {
  const post = await sandbox.AssistantWordPress.readDailyLogPost(new Date("2026-10-17T12:00:00"));
  assert.equal(post.id, 33);
  assert.equal(post.link, "https://andrew.local/2026/10/17/october-17-saturday-2026/");
  assert.notEqual(post.link, "https://andrew.local/");
  assert(commands.some(args => args[0] === "post" && args[1] === "url" && args[2] === "33"));
  assert(!commands.some(args => args[0] === "post" && args[1] === "create"), "Preview must never create a post");
  console.log("wp-cli-preview-harness: PASS (real permalink, no GUID or writing)");
})().catch(error => {console.error(error); process.exit(1);});
