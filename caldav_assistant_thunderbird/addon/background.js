"use strict";

const SPACE_NAME = "thunderbird_caldav_lab";

async function diagnostic(event, details = {}) {
  try {
    await browser.ThunderbirdCalDAV.writeDiagnostic("background", event, details);
  } catch (error) {
    console.warn("[CalDAVAssistant] diagnostics unavailable", error);
  }
}

async function activateTaskEnhancements() {
  await browser.TaskFix.activate();
}

async function ensureWorkspace() {
  if (!browser.spaces) {
    console.warn("[CalDAVAssistant] spaces API is unavailable");
    return null;
  }
  const existing = await browser.spaces.query({
    isSelfOwned: true,
    name: SPACE_NAME,
  });
  if (existing.length) {
    if (browser.spaces.update) {
      try {
        await browser.spaces.update(existing[0].id, {title: "CalDAV Assistant"});
      } catch (error) {
        console.warn("[CalDAVAssistant] could not update existing Space title", error);
      }
    }
    return existing[0];
  }

  try {
    return await browser.spaces.create(
      SPACE_NAME,
      "workspace.html",
      {title: "CalDAV Assistant"}
    );
  } catch (error) {
    const raced = await browser.spaces.query({
      isSelfOwned: true,
      name: SPACE_NAME,
    });
    if (raced.length) {
      await diagnostic("space.create-race-reused", {
        spaceId: raced[0].id ?? null,
        message: error?.message || String(error),
      });
      return raced[0];
    }
    throw error;
  }
}

async function startup() {
  const manifest = browser.runtime.getManifest();
  await diagnostic("startup.begin", {version: manifest.version});
  try {
    await activateTaskEnhancements();
    const space = await ensureWorkspace();

    let wordpressOutbox = null;
    try {
      wordpressOutbox =
        await globalThis.AssistantWordPressOutbox?.flushOutbox?.() || null;
    } catch (error) {
      wordpressOutbox = {
        success: false,
        error: error?.message || String(error),
      };
    }

    await diagnostic("startup.success", {
      version: manifest.version,
      spaceId: space?.id ?? null,
      wordpressOutbox,
    });
  } catch (error) {
    await diagnostic("startup.error", {
      version: manifest.version,
      name: error?.name || "Error",
      message: error?.message || String(error),
    });
    throw error;
  }
}

let startupPromise = null;

function startupOnce() {
  if (!startupPromise) {
    startupPromise = startup().catch(error => {
      startupPromise = null;
      throw error;
    });
  }
  return startupPromise;
}

browser.runtime.onInstalled.addListener(() => startupOnce().catch(console.error));
browser.runtime.onStartup.addListener(() => startupOnce().catch(console.error));
startupOnce().catch(error => console.error("[CalDAVAssistant] startup failed", error));
