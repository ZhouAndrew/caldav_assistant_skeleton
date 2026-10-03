"use strict";

/*
 * Clean-room VTODO adapter.
 *
 * Implementation references:
 * - Thunderbird esr153 calendar/base/public/calICalendar.idl
 * - Thunderbird esr153 calendar/base/public/calICalendarManager.idl
 * - Thunderbird esr153 calendar/base/src/CalTodo.sys.mjs
 * - Thunderbird esr153 calendar/base/src/CalRecurrenceInfo.sys.mjs
 *
 * This API intentionally exposes VTODO operations only. Workflow state,
 * WordPress, UI state and VEVENT work-history concepts do not belong here.
 */

var { ExtensionCommon } = ChromeUtils.importESModule(
  "resource://gre/modules/ExtensionCommon.sys.mjs"
);
var { cal } = ChromeUtils.importESModule(
  "resource:///modules/calendar/calUtils.sys.mjs"
);

const TASK_STATUSES = new Set([
  "",
  "NEEDS-ACTION",
  "IN-PROCESS",
  "COMPLETED",
  "CANCELLED",
]);

function calendarById(calendarId) {
  const id = String(calendarId || "");
  const calendar = cal.manager.getCalendarById(id);
  if (!calendar) {
    throw new Error(`Calendar not found: ${id}`);
  }
  return calendar;
}

function calendarSupportsTasks(calendar) {
  return calendar.getProperty("capabilities.tasks.supported") !== false;
}

function calendarView(calendar) {
  return {
    id: String(calendar.id || ""),
    name: String(calendar.name || ""),
    type: String(calendar.type || ""),
    disabled: Boolean(calendar.getProperty("disabled")),
    readOnly: Boolean(calendar.readOnly),
    supportsTasks: calendarSupportsTasks(calendar),
  };
}

function dateView(value) {
  if (!value) return null;
  return {
    icalString: String(value.icalString || ""),
    isDate: Boolean(value.isDate),
    timezone: String(value.timezone?.tzid || ""),
  };
}

function taskView(item) {
  if (!item?.isTodo?.()) {
    throw new Error("Calendar item is not a VTODO.");
  }

  const calendar = item.calendar?.superCalendar || item.calendar;
  return {
    uid: String(item.id || ""),
    calendarId: String(calendar?.id || ""),
    calendarName: String(calendar?.name || ""),
    title: String(item.title || ""),
    status: String(item.getProperty("STATUS") || item.status || "").toUpperCase(),
    percentComplete: Number(item.percentComplete || 0),
    description: String(item.getProperty("DESCRIPTION") || ""),
    priority: Number(item.priority || 0),
    categories: item.getCategories().map(value => String(value)),
    start: dateView(item.entryDate),
    due: dateView(item.dueDate),
    completedDate: dateView(item.completedDate),
    recurring: Boolean(item.recurrenceInfo || item.recurrenceId),
    recurrenceId: String(item.recurrenceId?.icalString || ""),
  };
}

function parseRecurrenceId(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  try {
    return cal.createDateTime(text);
  } catch {
    throw new Error(`Invalid RECURRENCE-ID: ${text}`);
  }
}

async function resolveTask(calendarId, uid, recurrenceId = "") {
  const calendar = calendarById(calendarId);
  const master = await calendar.getItem(String(uid || ""));
  if (!master) {
    throw new Error(`VTODO not found: ${String(uid || "")}`);
  }
  if (!master.isTodo?.()) {
    throw new Error(`Calendar item is not a VTODO: ${String(uid || "")}`);
  }

  const rid = parseRecurrenceId(recurrenceId);
  if (!rid) return master;

  if (!master.recurrenceInfo) {
    throw new Error(
      `RECURRENCE-ID requested for non-recurring VTODO: ${String(uid || "")}`
    );
  }
  const occurrence = master.recurrenceInfo.getOccurrenceFor(rid);
  if (!occurrence) {
    throw new Error(
      `VTODO occurrence not found: ${String(uid || "")} @ ${String(recurrenceId)}`
    );
  }
  return occurrence;
}

function normalizeStatus(value) {
  const status = String(value ?? "").trim().toUpperCase();
  if (!TASK_STATUSES.has(status)) {
    throw new Error(`Unsupported VTODO STATUS: ${status}`);
  }
  return status;
}

function normalizePercent(value) {
  const percent = Number(value);
  if (
    !Number.isFinite(percent) ||
    !Number.isInteger(percent) ||
    percent < 0 ||
    percent > 100
  ) {
    throw new Error("PERCENT-COMPLETE must be an integer from 0 to 100.");
  }
  return percent;
}

function setDescription(item, value) {
  const description = String(value ?? "");
  if (description === "") item.deleteProperty("DESCRIPTION");
  else item.setProperty("DESCRIPTION", description);
}

function applyWorkflowPatch(item, patch) {
  if (!patch || typeof patch !== "object") {
    throw new Error("Task patch must be an object.");
  }

  const allowed = new Set(["description", "status", "percentComplete"]);
  for (const key of Object.keys(patch)) {
    if (!allowed.has(key)) {
      throw new Error(`Unsupported VTODO workflow field: ${key}`);
    }
  }

  const hasStatus = Object.prototype.hasOwnProperty.call(patch, "status");
  const hasPercent = Object.prototype.hasOwnProperty.call(
    patch,
    "percentComplete"
  );
  const status = hasStatus ? normalizeStatus(patch.status) : null;
  const percent = hasPercent ? normalizePercent(patch.percentComplete) : null;

  if (status === "COMPLETED" && hasPercent && percent !== 100) {
    throw new Error("COMPLETED VTODO must use PERCENT-COMPLETE=100.");
  }
  if (status !== null && status !== "COMPLETED" && percent === 100) {
    throw new Error("Non-completed VTODO cannot use PERCENT-COMPLETE=100.");
  }
  if (status === null && percent === 100) {
    throw new Error(
      "PERCENT-COMPLETE=100 requires an explicit STATUS=COMPLETED transition."
    );
  }

  if (Object.prototype.hasOwnProperty.call(patch, "description")) {
    setDescription(item, patch.description);
  }

  if (status === "COMPLETED") {
    item.isCompleted = true;
  } else if (status !== null) {
    if (item.isCompleted) {
      // Thunderbird CalTodo.isCompleted=false clears COMPLETED, STATUS and
      // PERCENT-COMPLETE. Re-apply the intended non-completed values below.
      item.isCompleted = false;
    }
    if (status === "") item.deleteProperty("STATUS");
    else item.status = status;
  }

  if (hasPercent) {
    item.percentComplete = percent;
  }

  return item;
}

function parseRangeDate(value, field) {
  const text = String(value || "").trim();
  if (!text) return null;
  try {
    return cal.createDateTime(text);
  } catch {
    throw new Error(`Invalid ${field}: ${text}`);
  }
}

async function listTasks(options = {}) {
  const requestedCalendar = String(options?.calendarId || "");
  const includeCompleted = options?.includeCompleted !== false;
  const expandOccurrences = Boolean(options?.expandOccurrences);

  let filter = Ci.calICalendar.ITEM_FILTER_TYPE_TODO;
  filter |= includeCompleted
    ? Ci.calICalendar.ITEM_FILTER_COMPLETED_ALL
    : Ci.calICalendar.ITEM_FILTER_COMPLETED_NO;

  let rangeStart = null;
  let rangeEnd = null;
  if (expandOccurrences) {
    rangeStart = parseRangeDate(options?.rangeStart, "rangeStart");
    rangeEnd = parseRangeDate(options?.rangeEnd, "rangeEnd");
    if (!rangeStart || !rangeEnd) {
      throw new Error(
        "expandOccurrences requires finite rangeStart and rangeEnd."
      );
    }
    filter |= Ci.calICalendar.ITEM_FILTER_CLASS_OCCURRENCES;
  }

  const calendars = requestedCalendar
    ? [calendarById(requestedCalendar)]
    : cal.manager.getCalendars();

  const tasks = [];
  for (const calendar of calendars) {
    if (
      Boolean(calendar.getProperty("disabled")) ||
      !calendarSupportsTasks(calendar)
    ) {
      continue;
    }
    const items = await calendar.getItemsAsArray(
      filter,
      0,
      rangeStart,
      rangeEnd
    );
    for (const item of items) {
      if (item?.isTodo?.()) tasks.push(taskView(item));
    }
  }
  return tasks;
}

async function updateTask(calendarId, uid, recurrenceId, patch) {
  const oldItem = await resolveTask(calendarId, uid, recurrenceId);
  const newItem = oldItem.clone().QueryInterface(Ci.calITodo);
  applyWorkflowPatch(newItem, patch);

  // Pass oldItem deliberately: calICalendar.modifyItem uses it for revision
  // checking and rejects concurrent modifications instead of overwriting them.
  const stored = await oldItem.calendar.modifyItem(newItem, oldItem);
  return taskView(stored);
}

this.ThunderbirdTasks = class extends ExtensionCommon.ExtensionAPI {
  getAPI() {
    return {
      ThunderbirdTasks: {
        listCalendars: async () =>
          cal.manager.getCalendars().map(calendarView),

        listTasks,

        getTask: async (calendarId, uid, recurrenceId = "") =>
          taskView(await resolveTask(calendarId, uid, recurrenceId)),

        updateTask,
      },
    };
  }
};
