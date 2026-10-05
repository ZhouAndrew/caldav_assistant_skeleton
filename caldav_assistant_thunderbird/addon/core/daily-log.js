"use strict";

(() => {
  function errorText(error) {
    return String(error?.message || error || "Unknown error");
  }

  function receiptStep(receipt, operation, success, details = {}) {
    if (!receipt?.steps) return;
    receipt.steps.push({
      timestamp: new Date().toISOString(),
      component: "WordPress",
      operation,
      success,
      details,
    });
  }

  function asDate(value) {
    if (!value) return null;
    if (value instanceof Date) {
      return Number.isNaN(value.getTime()) ? null : value;
    }
    if (typeof value === "number") {
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? null : date;
    }

    const text = String(value?.icalString || value?.iso || value || "").trim();
    const match = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/.exec(text);
    if (match) {
      return new Date(
        Number(match[1]),
        Number(match[2]) - 1,
        Number(match[3]),
        Number(match[4]),
        Number(match[5]),
        Number(match[6])
      );
    }

    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatTime(date) {
    return (
      String(date.getHours()).padStart(2, "0") + ":" +
      String(date.getMinutes()).padStart(2, "0")
    );
  }

  function nextLocalMidnight(date) {
    return new Date(
      date.getFullYear(),
      date.getMonth(),
      date.getDate() + 1,
      0, 0, 0, 0
    );
  }

  function splitByLocalDate(start, end) {
    const parts = [];
    let cursor = new Date(start.getTime());
    const finalEnd = end.getTime() < start.getTime()
      ? new Date(start.getTime())
      : end;

    while (cursor.getTime() < finalEnd.getTime()) {
      const midnight = nextLocalMidnight(cursor);
      const partEnd = new Date(Math.min(finalEnd.getTime(), midnight.getTime()));
      parts.push({start: new Date(cursor), end: partEnd});
      cursor = partEnd;
    }

    if (!parts.length) {
      parts.push({start: new Date(start), end: new Date(finalEnd)});
    }
    return parts;
  }

  function safeMarker(value) {
    return String(value || "")
      .replace(/[^A-Za-z0-9_.:-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 180);
  }

  function payloadFor(task, event, start, end) {
    const dateKey = AssistantStorage.localDateKey(start);
    return {
      type: "work-session",
      version: 1,
      taskUid: String(task?.id || event?.taskUid || ""),
      taskTitle: String(task?.title || "(untitled task)"),
      workEventUid: String(event?.id || ""),
      dateKey,
      startIso: start.toISOString(),
      endIso: end.toISOString(),
      content:
        `${formatTime(start)}–${formatTime(end)} ${String(task?.title || "(untitled task)")}`,
      marker: safeMarker(
        `caldav-assistant-work-${event?.id || "unknown"}-${dateKey}`
      ),
    };
  }

  async function appendPayload(payload) {
    return AssistantWordPress.createLog({
      content: payload.content,
      files: [],
      date: new Date(payload.startIso),
      prefixTime: payload.prefixTime === true,
      marker: payload.marker,
    });
  }

  async function queuePayload(payload, error) {
    return AssistantStorage.enqueueWordPressOutbox({
      payload,
      attempts: 1,
      lastError: errorText(error),
    });
  }

  async function recordClosedWorkSession(task, event, receipt = null) {
    const config = await AssistantWordPress.getConfig();
    if (config.dailyWorkLogEnabled === false) {
      receiptStep(receipt, "daily work log disabled", true, {
        workEventUid: event?.id || null,
      });
      return {success: true, skipped: true, reason: "disabled"};
    }

    const start = asDate(event?.start);
    const end = asDate(event?.end);
    if (!start || !end) {
      receiptStep(receipt, "daily work log unavailable", false, {
        workEventUid: event?.id || null,
        reason: "Closed Work VEVENT is missing a readable start/end.",
      });
      return {success: false, skipped: true, reason: "invalid-session"};
    }

    const results = [];
    for (const part of splitByLocalDate(start, end)) {
      const payload = payloadFor(task, event, part.start, part.end);
      try {
        const result = await appendPayload(payload);
        if (!result?.success) {
          const queued = await queuePayload(
            payload,
            result?.summary || "WordPress append failed"
          );
          receiptStep(receipt, "queue daily work log", false, {
            workEventUid: event?.id || null,
            date: payload.dateKey,
            outboxId: queued.id,
            error: result?.summary || "WordPress append failed",
          });
          results.push({success: false, queued: true, payload, result});
          continue;
        }

        receiptStep(receipt, "append daily work log", true, {
          workEventUid: event?.id || null,
          date: payload.dateKey,
          postId: result.post?.id || null,
          postTitle: result.post?.title || "",
          deduplicated: Boolean(result.deduplicated),
          content: payload.content,
        });
        results.push({success: true, payload, result});
      } catch (error) {
        const queued = await queuePayload(payload, error);
        receiptStep(receipt, "queue daily work log", false, {
          workEventUid: event?.id || null,
          date: payload.dateKey,
          outboxId: queued.id,
          error: errorText(error),
        });
        results.push({
          success: false,
          queued: true,
          payload,
          error: errorText(error),
        });
      }
    }

    return {
      success: results.every(item => item.success),
      queued: results.some(item => item.queued),
      results,
    };
  }

  async function flushOutbox() {
    const records = await AssistantStorage.listWordPressOutbox();
    let sent = 0;
    let failed = 0;

    for (const item of records) {
      try {
        const result = await appendPayload(item.payload);
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

  globalThis.AssistantDailyLog = Object.freeze({
    recordClosedWorkSession,
    flushOutbox,
  });
})();
