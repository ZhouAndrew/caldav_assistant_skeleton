"use strict";

(() => {
  function errorText(error) {
    return String(error?.message || error || "Unknown error");
  }

  async function appendLegacyPayload(payload) {
    const when = payload?.startIso ? new Date(payload.startIso) : new Date();
    return AssistantWordPress.createLog({
      content: String(payload?.content || ""),
      files: [],
      date: Number.isNaN(when.getTime()) ? new Date() : when,
      prefixTime: false,
      marker: String(payload?.marker || ""),
    });
  }

  async function flushOutbox() {
    const records = await AssistantStorage.listWordPressOutbox();
    let sent = 0;
    let failed = 0;

    for (const item of records) {
      try {
        const result = await appendLegacyPayload(item.payload);
        if (!result?.success) {
          throw new Error(result?.summary || "WordPress append failed");
        }
        await AssistantStorage.removeWordPressOutbox(item.id);
        sent++;
      } catch (error) {
        failed++;
        await AssistantStorage.updateWordPressOutbox(item.id, {
          attempts: Number(item.attempts || 0) + 1,
          lastError: errorText(error),
        });
      }
    }

    return {
      success: failed === 0,
      processed: records.length,
      sent,
      failed,
    };
  }

  // Compatibility-only transport for entries queued by 0.3.15 and earlier.
  // New Task actions never create Work Session payloads or inspect VEVENTs.
  globalThis.AssistantWordPressOutbox = Object.freeze({
    flushOutbox,
  });
})();
