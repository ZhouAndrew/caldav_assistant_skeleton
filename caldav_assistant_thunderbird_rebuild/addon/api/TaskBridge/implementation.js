"use strict";

const {ExtensionCommon} = ChromeUtils.importESModule(
  "resource://gre/modules/ExtensionCommon.sys.mjs"
);
const {cal} = ChromeUtils.importESModule(
  "resource:///modules/calendar/calUtils.sys.mjs"
);

function text(value) {
  return value === null || value === undefined ? "" : String(value);
}

function requireRef(ref) {
  const calendarId = text(ref?.calendarId);
  const uid = text(ref?.uid);
  const recurrenceId = text(ref?.recurrenceId);

  if (!calendarId || !uid) {
    throw new Error("Task reference requires calendarId and uid.");
  }
  return {calendarId, uid, recurrenceId};
}

function calendarById(calendarId) {
  const calendar = cal.manager
    .getCalendars()
    .find(candidate => text(candidate.id) === calendarId);

  if (!calendar) {
    throw new Error("Calendar not found: " + calendarId);
  }
  return calendar;
}

function supportsTasks(calendar) {
  return calendar.getProperty("capabilities.tasks.supported") !== false;
}

function calendarWritable(calendar) {
  return supportsTasks(calendar) && cal.acl.isCalendarWritable(calendar);
}

function dateView(value) {
  if (!value) return null;
  return {
    icalString: text(value.icalString),
    timezone: text(value.timezone?.tzid),
    isDate: Boolean(value.isDate),
  };
}

function taskView(item) {
  const calendar = item.calendar?.superCalendar || item.calendar;
  const rawStatus = item.getProperty("STATUS");
  return {
    calendarId: text(calendar?.id),
    calendarName: text(calendar?.name),
    uid: text(item.id),
    recurrenceId: text(item.recurrenceId?.icalString),
    title: text(item.title),
    status: rawStatus ? text(rawStatus).toUpperCase() : null,
    completed: Boolean(item.isCompleted),
    percentComplete: Number(item.percentComplete || 0),
    description: text(item.getProperty("DESCRIPTION")),
    priority: Number(item.priority || 0),
    categories: Array.from(item.getCategories?.() || [], value => text(value)),
    start: dateView(item.entryDate),
    due: dateView(item.dueDate),
    completedDate: dateView(item.completedDate),
    recurring: Boolean(item.recurrenceInfo || item.recurrenceId),
    writable: Boolean(
      calendar &&
      calendarWritable(calendar) &&
      cal.acl.userCanModifyItem(item)
    ),
  };
}

function parseRange(value) {
  const raw = text(value).trim();
  if (!raw) return null;
  try {
    return cal.createDateTime(raw);
  } catch {
    throw new Error("Invalid calendar range value: " + raw);
  }
}

async function resolveTask(ref) {
  const normalized = requireRef(ref);
  const calendar = calendarById(normalized.calendarId);
  const parent = await calendar.getItem(normalized.uid);

  if (!parent || !parent.isTodo?.()) {
    throw new Error("VTODO not found: " + normalized.uid);
  }

  if (!normalized.recurrenceId) {
    return {calendar, item: parent};
  }

  if (!parent.recurrenceInfo) {
    throw new Error("Recurring occurrence requested for non-recurring VTODO.");
  }

  let recurrenceDate;
  try {
    recurrenceDate = cal.createDateTime(normalized.recurrenceId);
  } catch {
    throw new Error("Invalid recurrence id: " + normalized.recurrenceId);
  }

  const occurrence = parent.recurrenceInfo.getOccurrenceFor(recurrenceDate);
  if (!occurrence) {
    throw new Error(
      "VTODO occurrence not found: " +
      normalized.uid +
      " @ " +
      normalized.recurrenceId
    );
  }

  return {calendar, item: occurrence};
}

function normalizeStatus(value) {
  if (value === null || value === undefined || value === "") return null;
  const status = text(value).trim().toUpperCase();
  if (
    status !== "NEEDS-ACTION" &&
    status !== "IN-PROCESS" &&
    status !== "COMPLETED" &&
    status !== "CANCELLED"
  ) {
    throw new Error("Unsupported VTODO STATUS: " + status);
  }
  return status;
}

function normalizePercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0 || number > 100) {
    throw new Error("PERCENT-COMPLETE must be from 0 to 100.");
  }
  return Math.trunc(number);
}

function applyTaskChanges(item, changes) {
  if (!changes || typeof changes !== "object") {
    throw new Error("Task changes must be an object.");
  }

  if ("description" in changes) {
    if (changes.description === null || changes.description === undefined) {
      item.deleteProperty("DESCRIPTION");
    } else {
      item.setProperty("DESCRIPTION", text(changes.description));
    }
  }

  if ("status" in changes) {
    const status = normalizeStatus(changes.status);
    if (status === "COMPLETED") {
      item.isCompleted = true;
    } else {
      item.completedDate = null;
      if (status === null) {
        item.deleteProperty("STATUS");
      } else {
        item.status = status;
      }
    }
  }

  if ("percentComplete" in changes) {
    item.percentComplete = normalizePercent(changes.percentComplete);
  }
}

async function listCalendars() {
  return cal.manager.getCalendars().map(calendar => ({
    id: text(calendar.id),
    name: text(calendar.name),
    disabled: Boolean(calendar.getProperty("disabled")),
    readOnly: Boolean(calendar.readOnly),
    writable: Boolean(calendarWritable(calendar)),
    supportsTasks: Boolean(supportsTasks(calendar)),
  }));
}

async function listTasks(options = {}) {
  const calendarId = text(options?.calendarId);
  const includeOccurrences = Boolean(options?.includeOccurrences);
  const rangeStart = parseRange(options?.rangeStart);
  const rangeEnd = parseRange(options?.rangeEnd);

  if (includeOccurrences && (!rangeStart || !rangeEnd)) {
    throw new Error(
      "Occurrence expansion requires both rangeStart and rangeEnd."
    );
  }

  const calendars = cal.manager.getCalendars().filter(calendar =>
    supportsTasks(calendar) &&
    (!calendarId || text(calendar.id) === calendarId)
  );

  let filter =
    Ci.calICalendar.ITEM_FILTER_TYPE_TODO |
    Ci.calICalendar.ITEM_FILTER_COMPLETED_ALL;

  if (includeOccurrences) {
    filter |= Ci.calICalendar.ITEM_FILTER_CLASS_OCCURRENCES;
  }

  const result = [];
  for (const calendar of calendars) {
    const items = await calendar.getItemsAsArray(
      filter,
      0,
      rangeStart,
      rangeEnd
    );
    for (const item of items) {
      if (item?.isTodo?.()) result.push(taskView(item));
    }
  }

  return result;
}

async function getTask(ref) {
  const {item} = await resolveTask(ref);
  return taskView(item);
}

function samePrecondition(item, expected) {
  if (!expected || typeof expected !== "object") return false;
  const view = taskView(item);
  return (
    view.status === (expected.status ?? null) &&
    view.completed === Boolean(expected.completed) &&
    view.percentComplete === Number(expected.percentComplete || 0) &&
    view.description === text(expected.description)
  );
}

async function updateTask(ref, changes, expected) {
  const {calendar, item: oldItem} = await resolveTask(ref);

  if (
    !calendarWritable(calendar) ||
    !cal.acl.userCanModifyItem(oldItem)
  ) {
    return {ok: false, reason: "not-writable"};
  }

  if (!samePrecondition(oldItem, expected)) {
    return {ok: false, reason: "changed"};
  }

  const newItem = oldItem.clone();
  applyTaskChanges(newItem, changes);

  // Thunderbird's provider receives both the caller's old view and the clone.
  // This preserves its normal revision/ETag conflict checks instead of forcing
  // an overwrite with a null old item.
  await calendar.modifyItem(newItem, oldItem);

  // CalDAV providers may normalize the item during PUT. Always return a fresh
  // provider read rather than trusting the local clone.
  return {ok: true, task: await getTask(ref)};
}

var TaskBridge = class extends ExtensionCommon.ExtensionAPI {
  getAPI() {
    return {
      TaskBridge: {
        listCalendars,
        listTasks,
        getTask,
        updateTask,
      },
    };
  }
};
