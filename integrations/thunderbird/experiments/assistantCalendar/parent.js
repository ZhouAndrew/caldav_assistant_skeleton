/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/*
 * Narrow CalDAV Assistant Experiment API.
 *
 * Reads Thunderbird's already-open Calendar/Tasks collections.  It is deliberately
 * read-only: authoritative mutations still go through CalDAV Assistant Core.
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

function taskView(item) {
  const categories = categoriesOf(item);
  const status = String(item.status || "NEEDS-ACTION").toUpperCase();
  return {
    id: String(item.id || ""),
    calendarId: String(item.calendar?.superCalendar?.id || item.calendar?.id || ""),
    calendarName: String(item.calendar?.superCalendar?.name || item.calendar?.name || ""),
    summary: String(item.title || ""),
    status,
    completed: status == "COMPLETED" || Boolean(item.isCompleted),
    due: item.dueDate?.icalString || null,
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

function enabledCalendars() {
  return cal.manager
    .getCalendars()
    .filter(calendar => !calendar.getProperty("disabled"));
}

async function itemsFrom(calendars, filter) {
  const batches = await Promise.all(
    calendars.map(async calendar => {
      try {
        return await calendar.getItemsAsArray(filter, 0, null, null);
      } catch (error) {
        console.warn(
          "CalDAV Assistant: local calendar cache read failed",
          calendar.name,
          error
        );
        return [];
      }
    })
  );
  return batches.flat();
}

this.assistant_calendar = class extends ExtensionAPI {
  getAPI(context) {
    return {
      assistantCalendar: {
        async listTasks() {
          const filter =
            Ci.calICalendar.ITEM_FILTER_TYPE_TODO |
            Ci.calICalendar.ITEM_FILTER_COMPLETED_ALL;

          const items = await itemsFrom(enabledCalendars(), filter);
          return items
            .filter(item => item && item.isTodo && item.isTodo())
            .map(taskView);
        },

        async workState() {
          const calendars = enabledCalendars();
          const namedHistory = calendars.filter(
            calendar => String(calendar.name || "") === "CalDAV Assistant History"
          );
          // Normally the Assistant work collection has this name.  If the user
          // configured another collection, fall back to scanning enabled local
          // calendars; the category + description markers still prevent false hits.
          const workCalendars = namedHistory.length ? namedHistory : calendars;
          const filter = Ci.calICalendar.ITEM_FILTER_TYPE_EVENT;
          const items = await itemsFrom(workCalendars, filter);

          const work = [];
          for (const item of items) {
            if (!item || !item.isEvent || !item.isEvent()) continue;
            const taskId = taskIdFromWorkEvent(item);
            if (!taskId) continue;
            const categories = categoriesOf(item);
            work.push({
              taskId,
              open:
                categories.includes(OPEN_WORK_CATEGORY) &&
                !item.endDate,
            });
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
            cal.manager.addCalendarObserver(observer);
            return () => cal.manager.removeCalendarObserver(observer);
          },
        }).api(),
      },
    };
  }
};
