"use strict";

const fs = require("fs");
const vm = require("vm");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

if (!global.btoa) global.btoa = value => Buffer.from(value, "binary").toString("base64");
if (!global.atob) global.atob = value => Buffer.from(value, "base64").toString("binary");

const local = {};
const storageWrites = [];
let lastWpCliCall = null;
let httpRequestCalls = 0;
let wpCliCalls = 0;
let curlRequestCalls = 0;
let lastCurlRequest = null;
let forceRestNetworkFailure = false;
global.browser = {
  storage: {
    local: {
      async get(key) { return {[key]: local[key]}; },
      async set(values) { storageWrites.push(...Object.keys(values)); Object.assign(local, values); },
    },
  },
  permissions: {
    async contains() { return true; },
  },
  ThunderbirdCalDAV: {
    async httpRequest(details = {}) {
      httpRequestCalls++;
      if (forceRestNetworkFailure) {
        throw new Error("Privileged HTTP request failed: network status 2152398868");
      }
      const headers = new Headers(details.headers || {});
      let body = details.bodyText ?? undefined;
      if (details.bodyBase64) {
        body = Uint8Array.from(Buffer.from(details.bodyBase64, "base64"));
      }
      const response = await global.fetch(details.url, {
        method: details.method || "GET",
        headers,
        body,
      });
      return {
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        url: response.url || details.url,
        text: await response.text(),
      };
    },
    async curlRequest(details = {}) {
      curlRequestCalls++;
      lastCurlRequest = details;
      assert(details.insecureTls === true, "insecure curl bridge was called without explicit opt-in");
      const headers = new Headers(details.headers || {});
      let body = details.bodyText ?? undefined;
      if (details.bodyBase64) {
        body = Uint8Array.from(Buffer.from(details.bodyBase64, "base64"));
      }
      const response = await global.fetch(details.url, {
        method: details.method || "GET",
        headers,
        body,
      });
      return {
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        url: response.url || details.url,
        text: await response.text(),
      };
    },
    async runWpCli(details = {}) {
      wpCliCalls++;
      lastWpCliCall = details;
      const args = details.args || [];
      if (args[0] === "core" && args[1] === "is-installed") {
        return {exitCode: 0, stdout: "", stderr: ""};
      }
      if (args[0] === "option" && args[1] === "get" && args[2] === "blogname") {
        return {exitCode: 0, stdout: "Acceptance WP\n", stderr: ""};
      }
      return {exitCode: 1, stdout: "", stderr: "unexpected mocked wp command: " + args.join(" ")};
    },
  },
};

let nextPost = 100;
let nextMedia = 200;
const posts = new Map();
const media = new Map();

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {"Content-Type": "application/json"},
  });
}

global.fetch = async (url, options = {}) => {
  const parsed = new URL(url);
  const path = parsed.pathname.replace(/^.*\/wp-json\/wp\/v2/, "");
  const method = (options.method || "GET").toUpperCase();

  assert(options.headers.get("Authorization")?.startsWith("Basic "), "missing Basic auth");

  if (path === "/users/me" && method === "GET") {
    return jsonResponse({id: 7, name: "Acceptance User", slug: "acceptance"});
  }

  if (path === "/posts" && method === "GET") {
    const search = parsed.searchParams.get("search") || "";
    return jsonResponse(
      [...posts.values()].filter(post =>
        !search || String(post.title?.raw || post.title?.rendered || "").includes(search)
      )
    );
  }

  if (path === "/posts" && method === "POST") {
    const body = JSON.parse(options.body);
    const id = ++nextPost;
    const post = {
      id,
      status: body.status || "draft",
      link: `http://example.test/?p=${id}`,
      title: {raw: body.title || "", rendered: body.title || ""},
      content: {raw: body.content || "", rendered: body.content || ""},
    };
    posts.set(id, post);
    return jsonResponse(post, 201);
  }

  let match = /^\/posts\/(\d+)$/.exec(path);
  if (match) {
    const id = Number(match[1]);
    const post = posts.get(id);
    if (!post) return jsonResponse({message: "missing"}, 404);
    if (method === "GET") return jsonResponse(post);
    if (method === "POST") {
      const body = JSON.parse(options.body);
      if ("content" in body) post.content = {raw: body.content, rendered: body.content};
      if ("title" in body) post.title = {raw: body.title, rendered: body.title};
      if ("status" in body) post.status = body.status;
      return jsonResponse(post);
    }
    if (method === "DELETE") {
      posts.delete(id);
      return jsonResponse({deleted: true, previous: post});
    }
  }

  if (path === "/media" && method === "POST") {
    const id = ++nextMedia;
    const item = {
      id,
      source_url: `http://example.test/uploads/test-${id}.png`,
      post: 0,
    };
    media.set(id, item);
    return jsonResponse(item, 201);
  }

  match = /^\/media\/(\d+)$/.exec(path);
  if (match) {
    const id = Number(match[1]);
    const item = media.get(id);
    if (!item) return jsonResponse({message: "missing"}, 404);
    if (method === "GET") return jsonResponse(item);
    if (method === "POST") {
      const body = JSON.parse(options.body);
      if ("post" in body) item.post = body.post;
      return jsonResponse(item);
    }
    if (method === "DELETE") {
      media.delete(id);
      return jsonResponse({deleted: true, previous: item});
    }
  }

  return jsonResponse({message: `unhandled ${method} ${path}`}, 500);
};

global.window = global;

for (const path of ["addon/core/storage.js", "addon/core/wordpress.js"]) {
  vm.runInThisContext(fs.readFileSync(path, "utf8"), {filename: path});
}

(async () => {
  await AssistantWordPress.saveConfig({
    baseUrl: "http://example.test/wordpress/",
    username: "acceptance",
    applicationPassword: "secret-app-password",
  });

  await AssistantStorage.saveSettingsWithUndo({taskView: "completed"});
  assert(
    !JSON.stringify(local["caldavAssistant.settingsUndo"]).includes("secret-app-password"),
    "settings undo duplicated the WordPress application password"
  );
  await AssistantStorage.undoSettings();
  assert(
    (await AssistantStorage.getSettings()).wordpress?.applicationPassword === "secret-app-password",
    "targeted settings undo damaged unrelated WordPress configuration"
  );

  const quick = await AssistantWordPress.quickTest();
  assert(quick.success, "WordPress REST quick test failed");
  assert(quick.transport === "application-password", "auto transport did not select Application Password");
  assert(quick.logSaved === true, "WordPress quick result was not persistently logged");

  await AssistantWordPress.saveConfig({
    transport: "auto",
    baseUrl: "https://andrew.local",
    username: "acceptance",
    applicationPassword: "secret-app-password",
    wordpressPath: "/var/www/html/wordpress",
    wpCliCommand: "wp",
  });
  forceRestNetworkFailure = true;
  const restCallsBeforeFallback = httpRequestCalls;
  const wpCliCallsBeforeFallback = wpCliCalls;
  const fallbackQuick = await AssistantWordPress.quickTest();
  assert(fallbackQuick.success, "auto transport did not recover from REST network reset");
  assert(fallbackQuick.transport === "wp-cli", "auto transport did not report WP-CLI fallback");
  assert(httpRequestCalls === restCallsBeforeFallback + 1, "REST fallback did not start with one REST attempt");
  assert(wpCliCalls > wpCliCallsBeforeFallback, "REST network reset did not invoke WP-CLI fallback");

  const restCallsAfterFallback = httpRequestCalls;
  const secondFallbackQuick = await AssistantWordPress.quickTest();
  assert(secondFallbackQuick.success, "cached WP-CLI fallback quick test failed");
  assert(secondFallbackQuick.transport === "wp-cli", "cached fallback stopped reporting WP-CLI");
  assert(
    httpRequestCalls === restCallsAfterFallback,
    "cached WP-CLI fallback retried the broken REST transport"
  );

  await AssistantWordPress.saveConfig({
    transport: "application-password",
    baseUrl: "https://andrew.local",
    username: "acceptance",
    applicationPassword: "secret-app-password",
    wordpressPath: "/var/www/html/wordpress",
    wpCliCommand: "wp",
  });
  const wpCliCallsBeforeStrictRest = wpCliCalls;
  const strictRestQuick = await AssistantWordPress.quickTest();
  assert(!strictRestQuick.success, "explicit Application Password mode hid the REST network error");
  assert(
    wpCliCalls === wpCliCallsBeforeStrictRest,
    "explicit Application Password mode unexpectedly fell back to WP-CLI"
  );
  forceRestNetworkFailure = false;

  const httpBeforeInsecure = httpRequestCalls;
  const wpCliBeforeInsecure = wpCliCalls;
  const curlBeforeInsecure = curlRequestCalls;
  await AssistantWordPress.saveConfig({
    transport: "application-password",
    baseUrl: "https://andrew.local",
    username: "acceptance",
    applicationPassword: "secret-app-password",
    allowUntrustedTls: true,
    wordpressPath: "/var/www/html/wordpress",
    wpCliCommand: "wp",
  });
  const insecureQuick = await AssistantWordPress.quickTest();
  assert(insecureQuick.success, "explicit local insecure HTTPS REST mode failed");
  assert(insecureQuick.transport === "application-password", "insecure REST changed transport identity");
  assert(insecureQuick.tlsVerification === "disabled-local", "insecure REST was not reported transparently");
  assert(curlRequestCalls === curlBeforeInsecure + 1, "insecure REST did not use curl bridge");
  assert(httpRequestCalls === httpBeforeInsecure, "insecure REST unexpectedly used Thunderbird HTTP bridge");
  assert(wpCliCalls === wpCliBeforeInsecure, "insecure REST unexpectedly fell back to WP-CLI");
  assert(lastCurlRequest?.url?.startsWith("https://andrew.local/"), "insecure REST used unexpected URL");

  await AssistantWordPress.saveConfig({
    transport: "application-password",
    baseUrl: "https://example.com",
    username: "acceptance",
    applicationPassword: "secret-app-password",
    allowUntrustedTls: true,
    wordpressPath: "/var/www/html/wordpress",
    wpCliCommand: "wp",
  });
  const publicInsecure = await AssistantWordPress.quickTest();
  assert(!publicInsecure.success, "insecure TLS mode was allowed for a public hostname");
  assert(
    /只允许|local|私有|局域网/i.test(publicInsecure.summary),
    "public-host insecure TLS rejection was not explained"
  );
  assert(curlRequestCalls === curlBeforeInsecure + 1, "public-host rejection reached curl bridge");

  await AssistantWordPress.saveConfig({
    transport: "wp-cli",
    wordpressPath: "/var/www/html/wordpress",
    wpCliCommand: "sudo -n -u www-data /usr/local/bin/wp",
  });
  const cliQuick = await AssistantWordPress.quickTest();
  assert(cliQuick.success, "WordPress WP-CLI quick test failed");
  assert(cliQuick.transport === "wp-cli", "explicit WP-CLI transport was not selected");
  assert(lastWpCliCall?.executable === "sudo", "legacy sudo WP-CLI executable was not preserved");
  assert(
    JSON.stringify(lastWpCliCall?.prefixArgs) === JSON.stringify(["-n", "-u", "www-data", "/usr/local/bin/wp"]),
    "legacy sudo WP-CLI prefix arguments were not preserved"
  );

  await AssistantWordPress.saveConfig({
    transport: "application-password",
    baseUrl: "http://example.test/wordpress/",
    username: "acceptance",
    applicationPassword: "secret-app-password",
    wordpressPath: "/var/www/html/wordpress",
    wpCliCommand: "wp",
  });

  const firstAuditWrite = storageWrites.findIndex(key => key.startsWith("caldavAssistant.audit."));
  const firstReceiptWrite = storageWrites.indexOf("caldavAssistant.lastReceipt");
  assert(
    firstAuditWrite >= 0 && firstReceiptWrite >= 0 && firstAuditWrite < firstReceiptWrite,
    "WordPress result cache was written before the persistent log"
  );

  const full = await AssistantWordPress.fullWriteTest();
  assert(full.success, "WordPress full write test failed");
  assert(posts.size === 0, "full write test left a TEST post behind");
  assert(media.size === 0, "full write test left TEST media behind");
  assert(
    full.steps.some(step => step.name === "update + read-back TEST post"),
    "full test did not verify post update"
  );
  assert(
    full.steps.some(step => step.name === "read TEST media"),
    "full test did not verify media read-back"
  );

  const file = new Blob(["attachment"], {type: "text/plain"});
  Object.defineProperty(file, "name", {value: "note.txt"});
  const image = new Blob(["png"], {type: "image/png"});
  Object.defineProperty(image, "name", {value: "photo.png"});
  const firstLog = await AssistantWordPress.createLog({
    content: "Completed work.",
    files: [file, image],
  });
  assert(firstLog.success, "WordPress first log append failed");
  assert(firstLog.post?.id, "WordPress log receipt has no Post ID");
  assert(firstLog.post.createdToday === true, "first log did not create today's daily post");
  assert(firstLog.media?.[0]?.id, "WordPress log receipt has no Media ID");
  assert(firstLog.media?.[1]?.id, "WordPress image receipt has no Media ID");
  assert(firstLog.media.every(item => item.parent === firstLog.post.id), "media parent Post ID was not reported");

  const dailyPostId = firstLog.post.id;

  // The older wp-cli finder accepts month abbreviation, arbitrary spacing,
  // and title token order. Keep the add-on compatible with those existing
  // daily posts instead of creating a duplicate.
  const createdTitleParts = String(firstLog.post.title || "").trim().split(/\s+/);
  assert(createdTitleParts.length === 4, "unexpected generated daily title");
  const [monthName, dayNumber, weekdayName, yearNumber] = createdTitleParts;
  posts.get(dailyPostId).title = {
    raw: weekdayName + " " + monthName.slice(0, 3) + " " + dayNumber + " " + yearNumber,
    rendered: weekdayName + " " + monthName.slice(0, 3) + " " + dayNumber + " " + yearNumber,
  };

  const secondLog = await AssistantWordPress.createLog({
    content: "Second work entry.",
    files: [],
  });
  assert(secondLog.success, "WordPress second log append failed");
  assert(secondLog.post?.id === dailyPostId, "second log created a different WordPress post");
  assert(secondLog.post.createdToday === false, "second log did not reuse today's daily post");
  assert(posts.size === 1, "one-by-one logging created more than one daily WordPress post");
  const dailyPost = posts.get(dailyPostId);
  const dailyContent = dailyPost?.content?.raw || "";
  const title = firstLog.post.title || "";
  assert(
    /^[A-Za-z]+ \d{1,2} [A-Za-z]+ \d{4}$/.test(title),
    "new daily WordPress post title no longer matches the existing helper format"
  );
  assert(dailyContent.includes("Completed work."), "first log entry was lost");
  assert(dailyContent.includes("Second work entry."), "second log entry was not appended");
  assert(/<p>\d{2}:\d{2} Completed work\.<\/p>/.test(dailyContent), "log entry has no HH:MM prefix");
  assert(dailyContent.includes("<!-- wp:file"), "generic attachment is not a Gutenberg file block");
  assert(dailyContent.includes("note.txt"), "attachment link was not appended to the daily log");
  assert(dailyContent.includes("<!-- wp:image"), "image attachment is not a Gutenberg image block");
  assert(dailyContent.includes("photo.png"), "image attachment alt text was not preserved");

  const audits = await AssistantStorage.listAudit();
  assert(audits.some(row => row.scope === "wordpress"), "WordPress log was not audited");
  assert(
    !JSON.stringify(audits).includes("secret-app-password"),
    "WordPress application password leaked into audit logs"
  );

  console.log("wordpress-connector-harness: PASS");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
