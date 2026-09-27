/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/*
 * Narrow CalDAV Assistant Experiment API.
 *
 * Thunderbird does not currently expose calendar/task collections through its
 * built-in WebExtension API. This adapter intentionally exposes only one fast,
 * read-only projection of Thunderbird's already-open calendar collections.
 */
var {
  ExtensionCommon: { ExtensionAPI, EventManager },
} = ChromeUtils.importESModule("resource://gre/modules/ExtensionCommon.sys.mjs");
var { cal } = ChromeUtils.importESModule(
  "resource:///modules/calendar/calUtils.sys.mjs"
);

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

function taskView(item) {
  let categories = [];
  try {
    categories = item.getCategories() || [];
  } catch (_error) {}

  const status = String(item.status || "NEEDS-ACTION").toUpperCase();
  return {
    id: String(item.id || ""),
    calendarId: String(item.calendar?.superCalendar?.id || item.calendar?.id || ""),
    summary: String(item.title || ""),
    status,
    completed: status == "COMPLETED" || Boolean(item.isCompleted),
    due: item.dueDate?.icalString || null,
    priority: Number.isInteger(item.priority) ? item.priority : null,
    categories: Array.from(categories, value => String(value)),
    source: "thunderbird-calendar-cache",
  };
}

this.assistant_calendar = class extends ExtensionAPI {
  getAPI(context) {
    return {
      assistantCalendar: {
        async listTasks() {
          const calendars = cal.manager
            .getCalendars()
            .filter(calendar => !calendar.getProperty("disabled"));

          const filter =
            Ci.calICalendar.ITEM_FILTER_TYPE_TODO |
            Ci.calICalendar.ITEM_FILTER_COMPLETED_ALL;

          const batches = await Promise.all(
            calendars.map(async calendar => {
              try {
                return await calendar.getItemsAsArray(filter, 0, null, null);
              } catch (error) {
                console.warn(
                  "CalDAV Assistant: local task collection read failed",
                  calendar.name,
                  error
                );
                return [];
              }
            })
          );

          return batches
            .flat()
            .filter(item => item && item.isTodo && item.isTodo())
            .map(taskView);
        },

        onTasksChanged: new EventManager({
          context,
          name: "assistantCalendar.onTasksChanged",
          register: fire => {
            const notify = item => {
              if (!item || !item.isTodo || item.isTodo()) {
                fire.async();
              }
            };
            const observer = createCalendarObserver({
              onLoad() {
                fire.async();
              },
              onAddItem(item) {
                notify(item);
              },
              onModifyItem(newItem, oldItem) {
                notify(newItem || oldItem);
              },
              onDeleteItem(item) {
                notify(item);
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
