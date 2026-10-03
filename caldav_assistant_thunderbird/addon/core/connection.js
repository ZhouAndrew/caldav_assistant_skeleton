"use strict";

(() => {
  function errorText(error) {
    return String(error?.message || error || "Unknown error");
  }

  function toLocalInput(date = new Date()) {
    const pad = value => String(value).padStart(2, "0");
    return (
      date.getFullYear() + "-" +
      pad(date.getMonth() + 1) + "-" +
      pad(date.getDate()) + "T" +
      pad(date.getHours()) + ":" +
      pad(date.getMinutes()) + ":" +
      pad(date.getSeconds())
    );
  }

  async function diagnosticTraceSince(startedAt) {
    try {
      if (typeof browser.ThunderbirdCalDAV?.readDiagnostics !== "function") return [];
      const data = await browser.ThunderbirdCalDAV.readDiagnostics(5000);
      const floor = new Date(startedAt).getTime() - 100;
      const allowed = new Set(["provider", "taskfix-api", "taskfix-window"]);
      return (data?.lines || [])
        .map(line => {
          try {
            return JSON.parse(line);
          } catch (_error) {
            return null;
          }
        })
        .filter(Boolean)
        .filter(item => allowed.has(item.component))
        .filter(item => new Date(item.ts).getTime() >= floor)
        .map(item => ({
          timestamp: item.ts,
          component: item.component,
          event: item.event,
          success: !/error/i.test(String(item.event || "")),
          details: item.details || {},
        }));
    } catch (_error) {
      return [];
    }
  }

  async function finish(result) {
    result.trace = await diagnosticTraceSince(result.startedAt);
    result.completedAt = new Date().toISOString();
    return AssistantStorage.persistResult(result, "connection");
  }

  async function quickCalendarTest() {
    const result = {
      action: "connection.quick-calendar",
      success: false,
      startedAt: new Date().toISOString(),
      steps: [],
      summary: "",
    };
    try {
      const started = performance.now();
      const calendars = await browser.ThunderbirdCalDAV.listCalendars();
      result.steps.push({
        name: "list calendars",
        success: true,
        latencyMs: Math.round(performance.now() - started),
        count: calendars.length,
      });

      const readStarted = performance.now();
      const tasks = await browser.ThunderbirdCalDAV.listTasks();
      result.steps.push({
        name: "read existing VTODO",
        success: true,
        latencyMs: Math.round(performance.now() - readStarted),
        count: tasks.length,
      });

      result.success = true;
      result.summary = `Thunderbird Calendar provider is readable: ${calendars.length} calendars, ${tasks.length} tasks.`;
    } catch (error) {
      result.summary = `Calendar read test failed: ${errorText(error)}`;
      result.steps.push({name: "read", success: false, error: errorText(error)});
    }
    return finish(result);
  }

  async function fullCalendarWriteTest(calendarId) {
    const result = {
      action: "connection.full-calendar-write",
      success: false,
      startedAt: new Date().toISOString(),
      steps: [],
      summary: "",
      testEvent: null,
    };
    let created = null;
    try {
      const marker = `CALDAV-ASSISTANT-TEST-${Date.now()}`;
      const start = toLocalInput(new Date());
      const end = toLocalInput(new Date(Date.now() + 60_000));

      created = await browser.ThunderbirdCalDAV.createEvent(calendarId, {
        title: marker,
        start,
        end,
        categories: ["CalDAV Assistant", "Diagnostics"],
        description: "Temporary read/write verification event. Safe to delete.",
        workSession: false,
      });
      result.testEvent = {calendarId: created.calendarId, id: created.id};
      result.steps.push({name: "create TEST VEVENT", success: true, uid: created.id});

      const read = await browser.ThunderbirdCalDAV.getEvent(created.calendarId, created.id);
      if (read.title !== marker) throw new Error("Created VEVENT read-back title mismatch.");
      result.steps.push({name: "read TEST VEVENT", success: true, uid: read.id});

      const updatedTitle = marker + "-UPDATED";
      await browser.ThunderbirdCalDAV.updateEvent(created.calendarId, created.id, {
        title: updatedTitle,
      });
      const updated = await browser.ThunderbirdCalDAV.getEvent(
        created.calendarId,
        created.id
      );
      if (updated.title !== updatedTitle) {
        throw new Error("Updated VEVENT read-back title mismatch.");
      }
      result.steps.push({name: "update + read-back TEST VEVENT", success: true});

      await browser.ThunderbirdCalDAV.deleteEvent(created.calendarId, created.id);
      created = null;
      let missing = false;
      try {
        await browser.ThunderbirdCalDAV.getEvent(
          result.testEvent.calendarId,
          result.testEvent.id
        );
      } catch (_error) {
        missing = true;
      }
      if (!missing) throw new Error("TEST VEVENT still exists after delete.");
      result.steps.push({name: "delete + absence verification", success: true});

      result.success = true;
      result.summary = "Calendar write/read/update/delete verification passed. No VTODO was created.";
    } catch (error) {
      result.summary = `Calendar write test failed: ${errorText(error)}`;
      result.steps.push({name: "failure", success: false, error: errorText(error)});
      if (created) {
        try {
          await browser.ThunderbirdCalDAV.deleteEvent(created.calendarId, created.id);
          result.steps.push({name: "cleanup TEST VEVENT", success: true});
        } catch (cleanupError) {
          result.steps.push({
            name: "cleanup TEST VEVENT",
            success: false,
            error: errorText(cleanupError),
          });
        }
      }
    }
    return finish(result);
  }

  globalThis.AssistantConnection = Object.freeze({
    quickCalendarTest,
    fullCalendarWriteTest,
  });
})();
