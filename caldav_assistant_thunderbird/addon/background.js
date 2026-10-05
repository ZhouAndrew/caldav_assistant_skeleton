"use strict";

const SPACE_NAME = "thunderbird_caldav_lab";

async function diagnostic(event, details = {}) {
  try {
    await browser.ThunderbirdCalDAV.writeDiagnostic(
      "background",
      event,
      details
    );
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
    // onInstalled/onStartup can race in separate extension contexts. If another
    // context created the Space after our initial query, reuse it instead of
    // reporting a false startup failure.
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
        await globalThis.AssistantDailyLog?.flushOutbox?.() || null;
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

// All pages use the same serialized effect boundary.
browser.runtime.onMessage.addListener(message => {
  if (message?.type !== "assistant-work-action") return undefined;
  if (!["start","stop","complete","cancel"].includes(message.action)) return Promise.reject(new Error("Validation: invalid action"));
  return message.action === "start"
    ? AssistantExecutor.start(null,message.selectionAtClick)
    : AssistantExecutor[message.action]();
});

// The native toolbar is a UI entry point for the existing canonical executor.
const startRenderSequence=new Map();
browser.TaskFix.onSelectionChanged.addListener(async (windowId,selection)=>{
  const sequence=(startRenderSequence.get(windowId)||0)+1;startRenderSequence.set(windowId,sequence);
  try {
    const pointer=await AssistantStorage.getCurrentWorkId();
    if(startRenderSequence.get(windowId)!==sequence) return;
    browser.TaskFix.setStartState(windowId,AssistantActionPlan.deriveStartAvailability(pointer,selection),selection);
  } catch(error) {browser.TaskFix.setStartState(windowId,false,selection);console.error(error);}
});
browser.TaskFix.onStartRequested.addListener(async (_windowId,selection)=>{
  try {await AssistantExecutor.start(null,selection);}
  catch(error) {console.error(error);}
  finally {browser.TaskFix.requestStartState();}
});
browser.storage.onChanged.addListener(changes=>{
  if("caldavAssistant.currentWorkId" in changes) browser.TaskFix.requestStartState();
});
browser.TaskFix.requestStartState();
