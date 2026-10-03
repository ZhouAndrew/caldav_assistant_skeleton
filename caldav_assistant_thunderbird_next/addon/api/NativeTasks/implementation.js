"use strict";

const { ExtensionCommon } = ChromeUtils.importESModule(
  "resource://gre/modules/ExtensionCommon.sys.mjs"
);
const { cal } = ChromeUtils.importESModule(
  "resource:///modules/calendar/calUtils.sys.mjs"
);

const TASK_STATUSES = new Set([
  "NEEDS-ACTION",
  "IN-PROCESS",
  "COMPLETED",
  "CANCELLED",
]);

function calendarById(calendarId) {
  const calendar = cal.manager.getCalendarById(String(calendarId || ""));
  if (!calendar) {
    throw new Error("Calendar not found.");
  }
  return calendar;
}

function normalizedStatus(item) {
  const raw = String(item.status || "").trim().toUpperCase();
  if (TASK_STATUSES.has(raw)) return raw;
  return item.isCompleted ? "COMPLETED" : "NEEDS-ACTION";
}

function view(item, calendarId = "") {
  return {
    calendarId: String(calendarId || item.calendar?.id || ""),
    uid: String(item.id || ""),
    recurrenceId: String(item.recurrenceId?.icalString || ""),
    title: String(item.title || ""),
    description: String(item.descriptionText || ""),
    status: normalizedStatus(item),
    percentComplete: Number(item.percentComplete || 0),
  };
}

async function resolveTask(calendarId, uid, recurrenceId) {
  const calendar = calendarById(calendarId);
  const parent = await calendar.getItem(String(uid || ""));
  if (!parent) return null;
  if (!parent.isTodo?.()) {
    throw new Error("Requested calendar item is not a VTODO.");
  }

  const recurrence = String(recurrenceId || "").trim();
  if (!recurrence) return parent;
  if (!parent.recurrenceInfo) {
    throw new Error("Recurring occurrence requested for non-recurring VTODO.");
  }

  const recurrenceDate = cal.createDateTime(recurrence);
  const occurrence = parent.recurrenceInfo.getOccurrenceFor(recurrenceDate);
  if (!occurrence) {
    throw new Error("VTODO occurrence not found.");
  }
  return occurrence;
}

function applyPatch(item, patch) {
  const status = String(patch?.status || "").trim().toUpperCase();
  const percent = Number(patch?.percentComplete);

  if (!TASK_STATUSES.has(status)) {
    throw new Error("Unsupported VTODO status.");
  }
  if (!Number.isInteger(percent) || percent < 0 || percent > 100) {
    throw new Error("Invalid VTODO percentComplete.");
  }
  if (status !== "COMPLETED" && percent === 100) {
    throw new Error("Non-completed VTODO cannot have 100 percentComplete.");
  }

  item.descriptionText = String(patch?.description || "");

  if (status === "COMPLETED") {
    item.isCompleted = true;
    return;
  }

  item.isCompleted = false;
  item.status = status;
  item.percentComplete = percent;
}

var NativeTasks = class extends ExtensionCommon.ExtensionAPI {
  getAPI() {
    return {
      NativeTasks: {
        async getTask(calendarId, uid, recurrenceId) {
          const item = await resolveTask(calendarId, uid, recurrenceId);
          return item ? view(item, calendarId) : null;
        },

        async updateTask(calendarId, uid, recurrenceId, patch) {
          const oldItem = await resolveTask(calendarId, uid, recurrenceId);
          if (!oldItem) {
            throw new Error("VTODO not found.");
          }

          const nextItem = oldItem.clone();
          applyPatch(nextItem, patch);
          const stored = await oldItem.calendar.modifyItem(nextItem, oldItem);
          return view(stored, calendarId);
        },

        async scanStoredTasks() {
          const tasks = [];
          const failures = [];
          const filter =
            Ci.calICalendar.ITEM_FILTER_TYPE_TODO |
            Ci.calICalendar.ITEM_FILTER_COMPLETED_ALL;

          for (const calendar of cal.manager.getCalendars()) {
            const calendarId = String(calendar.id || "");
            try {
              if (calendar.getProperty?.("capabilities.tasks.supported") === false) {
                continue;
              }

              const parents = await calendar.getItemsAsArray(
                filter,
                0,
                null,
                null
              );

              for (const parent of parents) {
                if (!parent?.isTodo?.()) continue;
                tasks.push(view(parent, calendarId));

                const recurrenceInfo = parent.recurrenceInfo;
                if (!recurrenceInfo) continue;

                for (const recurrenceId of recurrenceInfo.getExceptionIds()) {
                  const exception =
                    recurrenceInfo.getExceptionFor(recurrenceId);
                  if (exception?.isTodo?.()) {
                    tasks.push(view(exception, calendarId));
                  }
                }
              }
            } catch (error) {
              failures.push({
                calendarId,
                message: String(error?.message || error),
              });
            }
          }

          return {
            tasks,
            complete: failures.length === 0,
            failures,
          };
        },
      },
    };
  }
};
