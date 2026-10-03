"use strict";

(async () => {
  const moduleUrl = browser.runtime.getURL("dist/startup.js");
  const {startCleanroom} = await import(moduleUrl);
  const report = await startCleanroom(browser);

  // Kept only in volatile background memory for diagnostics/UI to query later.
  // No second workflow state is persisted here.
  globalThis.__caldavAssistantCleanroomStartup = report;
})().catch(error => {
  console.error("[CalDAV Assistant cleanroom] startup failed", error);
});
