/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/*
 * Narrow CalDAV Assistant Experiment API.
 *
 * Reads Thunderbird's already-open Calendar/Tasks collections. It is deliberately
 * read-only: authoritative mutations still go through CalDAV Assistant Core.
 *
 * This file intentionally treats Thunderbird internals as fallible. Experiment APIs
 * can change between Thunderbird majors, so refreshSnapshot() converts privileged
 * exceptions into plain structured diagnostics that the WebExtension can fall back
 * from instead of surfacing only "An unexpected error occurred".
 */
var {
  ExtensionCommon: { ExtensionAPI, EventManager },
} = ChromeUtils.importESModule("resource://gre/modules/ExtensionCommon.sys.mjs");
var { cal } = ChromeUtils.importESModule(
  "resource:///modules/calendar/calUtils.sys.mjs"
);

const WORK_CATEGORY = "caldav-assistant-work";
const OPEN_WORK_CATEGORY = "caldav-assistant-work-open";
const DESCRIPTION_HEADER = "CalDAV Assistant Work Segment";
const TASK_PREFIX = "Task-UID: ";

function safeError(error) {
  if (error == null) return "Unknown Thunderbird error";
  const name = String(error.name || "").trim();
  const message = String(error.message || error).trim();
  let text = name && message && !message.startsWith(name + ":")
    ? name + ": " + message
    : message || name || "Unknown Thunderbird error";
  const result = error.result ?? error.resultCode ?? error.code;
  if (result != null && !text.includes(String(result))) {
    text += " [" + String(result) + "]";
  }
  return text;
}

function calendarManager() {
  if (cal?.manager && typeof cal.manager.getCalendars === "function") {
    return cal.manager;
  }
  try {
    const module = ChromeUtils.importESModule(
      "resource:///modules/CalCalendarManager.sys.mjs"
    );
    const manager = module.manager || module.CalCalendarManager;
    if (manager && typeof manager.getCalendars === "function") return manager;
  } catch (_error) {}
  throw new Error("Thunderbird Calendar Manager is unavailable");
}

function createCalendarObserver(methods = {}) {
  return Object.assign(
    {
      QueryInterface: ChromeUtils.generateQI(["calIObserver"]),
      onStartBatch() {},
      onEndBatch() {},
      onLoad() {},
      onAddItem() {},
      onModifyItem() {},
      onDeleteItem() {},
      onError() {},
      onPropertyChanged() {},
      onPropertyDeleting() {},
    },
    methods
  );
}

function categoriesOf(item) {
  try {
    return Array.from(item.getCategories() || [], value => String(value));
  } catch (_error) {
    return [];
  }
}

function isTodo(item) {
  try {
    return Boolean(
      item &&
      (typeof item.isTodo === "function" ? item.isTodo() : item.isTodo)
    );
  } catch (_error) {
    return false;
  }
}

function isEvent(item) {
  try {
    return Boolean(
      item &&
      (typeof item.isEvent === "function" ? item.isEvent() : item.isEvent)
    );
  } catch (_error) {
    return false;
  }
}

function taskView(item) {
  const categories = categoriesOf(item);
  const status = String(item.status || "NEEDS-ACTION").toUpperCase();
  let due = null;
  try {
    due = item.dueDate?.icalString || null;
  } catch (_error) {}
  return {
    id: String(item.id || ""),
    calendarId: String(item.calendar?.superCalendar?.id || item.calendar?.id || ""),
    calendarName: String(item.calendar?.superCalendar?.name || item.calendar?.name || ""),
    summary: String(item.title || ""),
    status,
    completed: status == "COMPLETED" || Boolean(item.isCompleted),
    due,
    priority: Number.isInteger(item.priority) ? item.priority : null,
    categories,
    source: "thunderbird-calendar-cache",
  };
}

function taskIdFromWorkEvent(item) {
  const categories = categoriesOf(item);
  if (!categories.includes(WORK_CATEGORY)) return null;

  let description = "";
  try {
    description = String(item.getProperty("DESCRIPTION") || "");
  } catch (_error) {}

  const lines = description.split(/\r?\n/);
  if (!lines.length || lines[0].trim() !== DESCRIPTION_HEADER) return null;
  for (const line of lines.slice(1)) {
    if (line.startsWith(TASK_PREFIX)) {
      const value = line.slice(TASK_PREFIX.length).trim();
      return value || null;
    }
  }
  return null;
}

function enabledCalendars(diagnostics = null) {
  const manager = calendarManager();
  const calendars = Array.from(manager.getCalendars() || []);
  const enabled = [];
  const failures = [];
  for (const calendar of calendars) {
    try {
      if (!calendar.getProperty("disabled")) enabled.push(calendar);
    } catch (error) {
      failures.push({
        calendar: String(calendar?.name || calendar?.id || "unknown"),
        error: safeError(error),
      });
    }
  }
  if (diagnostics) {
    diagnostics.steps.push({
      stage: "calendar-manager",
      success: failures.length === 0,
      calendarCount: calendars.length,
      enabledCount: enabled.length,
      failures,
    });
  }
  if (failures.length) {
    throw new Error(
      "Could not inspect " + failures.length + " Thunderbird calendar(s): " +
      failures[0].error
    );
  }
  return enabled;
}

async function itemsFromCalendar(calendar, filter) {
  if (typeof calendar.getItemsAsArray === "function") {
    return await calendar.getItemsAsArray(filter, 0, null, null);
  }

  if (typeof calendar.getItems === "function") {
    const stream = calendar.getItems(filter, 0, null, null);
    if (stream && typeof stream.getReader === "function") {
      const reader = stream.getReader();
      const values = [];
      try {
        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          if (Array.isArray(value)) values.push(...value);
          else if (value != null) values.push(value);
        }
      } finally {
        try {
          reader.releaseLock();
        } catch (_error) {}
      }
      return values;
    }
  }

  throw new Error("Calendar provider exposes neither getItemsAsArray() nor ReadableStream getItems()");
}

async function itemsFrom(calendars, filter, stage, diagnostics = null) {
  const rows = await Promise.all(
    calendars.map(async calendar => {
      try {
        const items = await itemsFromCalendar(calendar, filter);
        return {ok: true, items: Array.from(items || [])};
      } catch (error) {
        return {
          ok: false,
          calendar: String(calendar?.name || calendar?.id || "unknown"),
          error: safeError(error),
        };
      }
    })
  );

  const failures = rows.filter(row => !row.ok);
  const items = rows.filter(row => row.ok).flatMap(row => row.items);
  if (diagnostics) {
    diagnostics.steps.push({
      stage,
      success: failures.length === 0,
      calendarCount: calendars.length,
      itemCount: items.length,
      failures: failures.map(row => ({
        calendar: row.calendar,
        error: row.error,
      })),
    });
  }
  return {items, failures};
}

function workStateFromItems(items, workCalendars) {
  const work = [];
  for (const item of items) {
    if (!isEvent(item)) continue;
    const taskId = taskIdFromWorkEvent(item);
    if (!taskId) continue;
    const categories = categoriesOf(item);
    let open = false;
    try {
      open = categories.includes(OPEN_WORK_CATEGORY) && !item.endDate;
    } catch (_error) {
      open = false;
    }
    work.push({taskId, open});
  }

  const openIds = [...new Set(work.filter(item => item.open).map(item => item.taskId))];
  const workedIds = [...new Set(work.map(item => item.taskId))];
  return {
    currentTaskId: openIds.length === 1 ? openIds[0] : null,
    ambiguous: openIds.length > 1,
    openTaskIds: openIds,
    workedTaskIds: workedIds,
    eventCount: work.length,
    calendarCount: workCalendars.length,
    source: "thunderbird-calendar-cache",
  };
}

async function buildRefreshSnapshot() {
  const diagnostics = {steps: []};
  try {
    const calendars = enabledCalendars(diagnostics);
    const namedHistory = calendars.filter(
      calendar => String(calendar.name || "") === "CalDAV Assistant History"
    );
    const workCalendars = namedHistory.length ? namedHistory : calendars;

    const todoFilter =
      Ci.calICalendar.ITEM_FILTER_TYPE_TODO |
      Ci.calICalendar.ITEM_FILTER_COMPLETED_ALL;
    const eventFilter = Ci.calICalendar.ITEM_FILTER_TYPE_EVENT;

    const [taskRead, workRead] = await Promise.all([
      itemsFrom(calendars, todoFilter, "tasks-read", diagnostics),
      itemsFrom(workCalendars, eventFilter, "work-read", diagnostics),
    ]);

    const failures = [...taskRead.failures, ...workRead.failures];
    if (failures.length) {
      return {
        ok: false,
        error:
          "Thunderbird local calendar cache could not be fully verified: " +
          failures[0].error,
        diagnostics,
        source: "thunderbird-calendar-cache",
      };
    }

    const tasks = [];
    for (const item of taskRead.items) {
      if (!isTodo(item)) continue;
      try {
        tasks.push(taskView(item));
      } catch (error) {
        diagnostics.steps.push({
          stage: "task-serialization",
          success: false,
          error: safeError(error),
        });
        return {
          ok: false,
          error: "Thunderbird Task serialization failed: " + safeError(error),
          diagnostics,
          source: "thunderbird-calendar-cache",
        };
      }
    }

    const work = workStateFromItems(workRead.items, workCalendars);
    diagnostics.steps.push({
      stage: "snapshot",
      success: true,
      taskCount: tasks.length,
      workEventCount: work.eventCount,
    });
    return {
      ok: true,
      tasks,
      work,
      diagnostics,
      source: "thunderbird-calendar-cache",
    };
  } catch (error) {
    diagnostics.steps.push({
      stage: "refresh",
      success: false,
      error: safeError(error),
    });
    return {
      ok: false,
      error: safeError(error),
      diagnostics,
      source: "thunderbird-calendar-cache",
    };
  }
}

this.assistant_calendar = class extends ExtensionAPI {
  getAPI(context) {
    return {
      assistantCalendar: {
        async refreshSnapshot() {
          return await buildRefreshSnapshot();
        },

        async listTasks() {
          const diagnostics = {steps: []};
          const calendars = enabledCalendars(diagnostics);
          const filter =
            Ci.calICalendar.ITEM_FILTER_TYPE_TODO |
            Ci.calICalendar.ITEM_FILTER_COMPLETED_ALL;
          const result = await itemsFrom(calendars, filter, "tasks-read", diagnostics);
          if (result.failures.length) {
            throw new Error(
              "Thunderbird local Task read failed: " + result.failures[0].error
            );
          }
          return result.items.filter(isTodo).map(taskView);
        },

        async workState() {
          const diagnostics = {steps: []};
          const calendars = enabledCalendars(diagnostics);
          const namedHistory = calendars.filter(
            calendar => String(calendar.name || "") === "CalDAV Assistant History"
          );
          const workCalendars = namedHistory.length ? namedHistory : calendars;
          const filter = Ci.calICalendar.ITEM_FILTER_TYPE_EVENT;
          const result = await itemsFrom(workCalendars, filter, "work-read", diagnostics);
          if (result.failures.length) {
            throw new Error(
              "Thunderbird local Work-session read failed: " + result.failures[0].error
            );
          }
          return workStateFromItems(result.items, workCalendars);
        },

        onTasksChanged: new EventManager({
          context,
          name: "assistantCalendar.onTasksChanged",
          register: fire => {
            const observer = createCalendarObserver({
              onLoad() {
                fire.async();
              },
              onAddItem() {
                fire.async();
              },
              onModifyItem() {
                fire.async();
              },
              onDeleteItem() {
                fire.async();
              },
            });
            let manager = null;
            try {
              manager = calendarManager();
              manager.addCalendarObserver(observer);
            } catch (error) {
              console.warn(
                "CalDAV Assistant: calendar observer unavailable; manual refresh remains usable",
                safeError(error)
              );
              return () => {};
            }
            return () => {
              try {
                manager.removeCalendarObserver(observer);
              } catch (_error) {}
            };
          },
        }).api(),
      },
    };
  }
};
