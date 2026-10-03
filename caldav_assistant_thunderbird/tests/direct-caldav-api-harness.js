"use strict";

const fs = require("fs");
const vm = require("vm");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}
async function assertRejects(fn, pattern, message) {
  let error = null;
  try {
    await fn();
  } catch (caught) {
    error = caught;
  }
  assert(error, message + " (did not reject)");
  assert(pattern.test(String(error.message || error)), message + " (wrong error: " + error + ")");
}

class TestExtensionError extends Error {}

class TestEventManager {
  constructor(options) {
    this.options = options;
    TestEventManager.instances.push(this);
  }
  api() {
    return {__eventManager: this};
  }
}
TestEventManager.instances = [];

class DateTime {
  constructor(icalString = "") {
    this.icalString = icalString;
    this.timezone = {tzid: /Z$/.test(icalString) ? "UTC" : "floating"};
  }
  clone() {
    const value = new DateTime(this.icalString);
    value.timezone = this.timezone;
    return value;
  }
  getInTimezone(timezone) {
    const value = this.clone();
    value.timezone = timezone;
    return value;
  }
  compare(other) {
    const normalize = text => {
      if (/^\d{8}$/.test(text)) return text + "T000000";
      return text.replace(/Z$/, "");
    };
    return normalize(this.icalString).localeCompare(normalize(other.icalString));
  }
  get isDate() {
    return /^\d{8}$/.test(this.icalString);
  }
}

let uidCounter = 0;

class Item {
  constructor(kind) {
    this.kind = kind;
    this.id = "";
    this.calendar = null;
    this.title = "";
    this.priority = 0;
    this.percentComplete = 0;
    this.completedDate = null;
    this.dueDate = null;
    this.entryDate = null;
    this.startDate = null;
    this.endDate = null;
    this.recurrenceId = null;
    this.recurrenceInfo = null;
    this.parentItem = this;
    this._properties = new Map();
    this._categories = [];
  }
  isTodo() { return this.kind === "task"; }
  isEvent() { return this.kind === "event"; }
  get status() { return this._properties.get("STATUS") || ""; }
  set status(value) {
    if (value) this._properties.set("STATUS", String(value));
    else this._properties.delete("STATUS");
  }
  get isCompleted() {
    return this.completedDate !== null ||
      this.percentComplete === 100 ||
      this.status === "COMPLETED";
  }
  set isCompleted(value) {
    if (value) {
      this.status = "COMPLETED";
      this.percentComplete = 100;
      this.completedDate ||= new DateTime("20260930T120000Z");
    } else {
      this._properties.delete("COMPLETED");
      this._properties.delete("STATUS");
      this.percentComplete = 0;
      this.completedDate = null;
    }
  }
  getProperty(name) { return this._properties.get(name) ?? null; }
  setProperty(name, value) { this._properties.set(name, value); }
  deleteProperty(name) { this._properties.delete(name); }
  getCategories() { return [...this._categories]; }
  setCategories(values) { this._categories = [...values]; }
  clone() {
    const copy = new Item(this.kind);
    for (const key of [
      "id", "calendar", "title", "priority", "percentComplete",
      "completedDate", "dueDate", "entryDate", "startDate", "endDate",
      "recurrenceId"
    ]) {
      const value = this[key];
      copy[key] = value?.clone ? value.clone() : value;
    }
    copy.recurrenceInfo = this.recurrenceInfo;
    copy._properties = new Map(this._properties);
    copy._categories = [...this._categories];
    copy.parentItem = this.parentItem === this ? copy : this.parentItem;
    return copy;
  }
}

class Calendar {
  constructor(id, options = {}) {
    this.id = id;
    this.name = options.name || id;
    this.type = options.type || "caldav";
    this.readOnly = Boolean(options.readOnly);
    this.disabled = Boolean(options.disabled);
    this.supportsTasks = options.supportsTasks !== false;
    this.supportsEvents = options.supportsEvents !== false;
    this.items = new Map();
    this.calls = {read: 0, add: 0, modify: 0, delete: 0, get: 0};
    this.superCalendar = this;
  }
  getProperty(name) {
    if (name === "disabled") return this.disabled;
    if (name === "capabilities.tasks.supported") return this.supportsTasks;
    if (name === "capabilities.events.supported") return this.supportsEvents;
    return null;
  }
  async getItemsAsArray(filter, _count, start, end) {
    this.calls.read++;
    let values = [...this.items.values()];
    if (filter & Ci.calICalendar.ITEM_FILTER_TYPE_TODO) {
      values = values.filter(item => item.kind === "task");
    } else if (filter & Ci.calICalendar.ITEM_FILTER_TYPE_EVENT) {
      values = values.filter(item => item.kind === "event");
    }
    if (start) values = values.filter(item => !item.startDate || item.endDate?.compare(start) >= 0);
    if (end) values = values.filter(item => !item.startDate || item.startDate.compare(end) < 0);
    return values.map(item => item.clone());
  }
  async getItem(id) {
    this.calls.get++;
    const item = this.items.get(String(id));
    return item ? item.clone() : null;
  }
  async addItem(item) {
    this.calls.add++;
    assert(Boolean(item.id), "Thunderbird provider requires an item UID before addItem");
    const stored = item.clone();
    stored.calendar = this;
    stored.parentItem = stored;
    this.items.set(stored.id, stored);
    return stored.clone();
  }
  async modifyItem(newItem, oldItem) {
    this.calls.modify++;
    assert(this.items.has(String(oldItem.id)), "mock modify target missing");
    const stored = newItem.clone();
    stored.calendar = this;
    stored.parentItem = stored;
    this.items.set(stored.id, stored);
    return stored.clone();
  }
  async deleteItem(item) {
    this.calls.delete++;
    this.items.delete(String(item.id));
  }
}

const calendarA = new Calendar("cal-a", {name: "A"});
const calendarDisabled = new Calendar("cal-disabled", {disabled: true});
const calendarReadOnly = new Calendar("cal-ro", {readOnly: true});
const calendarNoTasks = new Calendar("cal-events-only", {supportsTasks: false});
const calendarNoEvents = new Calendar("cal-tasks-only", {supportsEvents: false});
const calendars = [
  calendarA,
  calendarDisabled,
  calendarReadOnly,
  calendarNoTasks,
  calendarNoEvents,
];

const displayedCalendarIds = new Set(["cal-a", "cal-ro", "cal-events-only", "cal-tasks-only"]);
const compositeCalendar = {
  getCalendars() {
    return calendars.filter(calendar => displayedCalendarIds.has(calendar.id));
  },
  getCalendarById(id) {
    return calendars.find(
      calendar => calendar.id === String(id) && displayedCalendarIds.has(calendar.id)
    ) || null;
  },
  addCalendar(calendar) {
    displayedCalendarIds.add(calendar.id);
  },
  removeCalendar(calendar) {
    displayedCalendarIds.delete(calendar.id);
  },
};

let nativeFilterConstructed = 0;
const nativeFilterApplications = [];
class FakeNativeCalFilter {
  constructor() {
    nativeFilterConstructed++;
    this.itemType = 0;
    this.selectedDate = null;
    this.filterText = "";
    this.filterName = "open";
  }
  applyFilter(name) {
    this.filterName = String(name);
    nativeFilterApplications.push(this.filterName);
  }
  getItems(calendar) {
    const self = this;
    return (async function* () {
      let items = await calendar.getItemsAsArray(
        self.itemType | Ci.calICalendar.ITEM_FILTER_COMPLETED_ALL,
        0,
        null,
        null
      );
      if (self.filterName === "open") {
        items = items.filter(item => !["COMPLETED", "CANCELLED"].includes(item.status));
      } else if (self.filterName === "completed") {
        items = items.filter(item => item.status === "COMPLETED");
      }
      if (self.filterText) {
        const query = self.filterText.toLowerCase();
        items = items.filter(item => String(item.title || "").toLowerCase().includes(query));
      }
      yield items;
    })();
  }
}
const mainMailWindow = {
  calFilter: FakeNativeCalFilter,
  document: {
    getElementById() {
      // Prove listNativeTasks does not require the built-in Tasks tab/tree to be open.
      return null;
    },
  },
};

let observer = null;
const cal = {
  manager: {
    getCalendars() { return calendars; },
    addCalendarObserver(value) { observer = value; },
    removeCalendarObserver(value) { if (observer === value) observer = null; },
  },
  createTodo() { return new Item("task"); },
  createEvent() { return new Item("event"); },
  getUUID() { return "uid-" + (++uidCounter); },
  createDateTime(value) { return new DateTime(value); },
  dtz: {
    defaultTimezone: {tzid: "Asia/Shanghai"},
    UTC: {tzid: "UTC"},
    now() {
      return new DateTime("20261002T120000");
    },
    jsDateToDateTime(value) {
      const iso = value.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
      return new DateTime(iso);
    },
  },
  view: {
    getCompositeCalendar(window) {
      assert(window === mainMailWindow, "native composite received unexpected mail window");
      return compositeCalendar;
    },
  },
  iterate: {
    streamValues(stream) {
      return stream;
    },
  },
};

global.Ci = {
  nsIIOService: {},
  nsIWindowMediator: {},
  calICalendar: {
    ITEM_FILTER_COMPLETED_YES: 1,
    ITEM_FILTER_COMPLETED_NO: 2,
    ITEM_FILTER_COMPLETED_ALL: 3,
    ITEM_FILTER_TYPE_TODO: 4,
    ITEM_FILTER_TYPE_EVENT: 8,
  },
};

global.Cc = {
  "@mozilla.org/network/io-service;1": {
    getService() {
      return {
        newURI(value) {
          const parsed = new URL(String(value));
          return {
            scheme: parsed.protocol.replace(/:$/, ""),
            host: parsed.hostname,
          };
        },
      };
    },
  },
  "@mozilla.org/appshell/window-mediator;1": {
    getService() {
      return {
        getMostRecentWindow(type) {
          assert(type === "mail:3pane", "unexpected Thunderbird window type");
          return mainMailWindow;
        },
      };
    },
  },
};

global.ChromeUtils = {
  importESModule(url) {
    if (url.includes("ExtensionCommon")) {
      return {
        ExtensionCommon: {
          ExtensionAPI: class {},
          EventManager: TestEventManager,
        },
      };
    }
    if (url.includes("ExtensionUtils")) {
      return {ExtensionUtils: {ExtensionError: TestExtensionError}};
    }
    if (url.includes("NetUtil")) {
      return {NetUtil: {
        newChannel() { throw new Error("NetUtil should not run in Calendar unit harness"); },
        asyncFetch() { throw new Error("NetUtil should not run in Calendar unit harness"); },
        readInputStreamToString() { return ""; },
      }};
    }
    if (url.includes("Subprocess")) {
      return {
        Subprocess: {
          async pathSearch(name) { return name; },
          async call() { throw new Error("Subprocess should not run in Calendar unit harness"); },
        },
      };
    }
    if (url.includes("calUtils")) {
      return {cal};
    }
    if (url.includes("CalTodo")) {
      return {CalTodo: class CalTodo extends Item {
        constructor() { super("task"); }
      }};
    }
    if (url.includes("CalEvent")) {
      return {CalEvent: class CalEvent extends Item {
        constructor() { super("event"); }
      }};
    }
    throw new Error("Unexpected module: " + url);
  },
  generateQI() { return () => {}; },
};

const source = fs.readFileSync(
  "addon/api/ThunderbirdCalDAV/implementation.js",
  "utf8"
);
vm.runInThisContext(source, {filename: "ThunderbirdCalDAV/implementation.js"});

const instance = new global.ThunderbirdCalDAV();
const api = instance.getAPI({}).ThunderbirdCalDAV;

(async () => {
  const listedCalendars = await api.listCalendars();
  assert(listedCalendars.length === 5, "must list every Thunderbird calendar");
  assert(listedCalendars.find(x => x.id === "cal-ro").readOnly, "read-only flag lost");
  assert(listedCalendars.find(x => x.id === "cal-disabled").disabled, "disabled flag lost");

  const seed = new Item("task");
  seed.id = "seed";
  seed.calendar = calendarA;
  seed.title = "Seed task";
  seed.status = "NEEDS-ACTION";
  calendarA.items.set(seed.id, seed);

  const hidden = new Item("task");
  hidden.id = "hidden";
  hidden.calendar = calendarDisabled;
  hidden.title = "Disabled task";
  calendarDisabled.items.set(hidden.id, hidden);

  const tasks = await api.listTasks();
  assert(tasks.some(x => x.id === "seed"), "enabled task was not listed");
  assert(!tasks.some(x => x.id === "hidden"), "disabled calendar leaked into all-calendar task list");

  const nativeTasks = await api.listNativeTasks({filter: "open", searchText: "Seed"});
  assert(nativeFilterConstructed === 1, "native calFilter was not instantiated");
  assert(nativeFilterApplications.at(-1) === "open", "native Task filter name was not delegated");
  assert(nativeTasks.length === 1 && nativeTasks[0].id === "seed", "native Task selector bridge lost matching task");

  const listedBeforeHide = await api.listCalendars();
  assert(
    listedBeforeHide.find(x => x.id === "cal-a").displayed === true,
    "native Calendar visibility was not exposed"
  );
  await api.setCalendarDisplayed("cal-a", false);
  assert(!displayedCalendarIds.has("cal-a"), "native Calendar hide did not use composite selector");
  const hiddenByNativeCalendar = await api.listNativeTasks({filter: "open", searchText: "Seed"});
  assert(hiddenByNativeCalendar.length === 0, "hidden native Calendar leaked into Task selector");
  await api.setCalendarDisplayed("cal-a", true);
  assert(displayedCalendarIds.has("cal-a"), "native Calendar show did not use composite selector");

  const createdTask = await api.createTask("cal-a", {
    title: "Created",
    due: "2026-10-05",
    status: "NEEDS-ACTION",
    priority: 5,
    categories: ["School", "School", "Math"],
    description: "direct Thunderbird provider",
  });
  assert(createdTask.id, "created task has no UID");
  assert(createdTask.title === "Created", "task title not persisted");
  assert(createdTask.due.icalString === "20261005", "date-only due conversion failed");
  assert(createdTask.priority === 5, "priority not persisted");
  assert(createdTask.categories.join(",") === "School,Math", "category de-duplication failed");
  assert(calendarA.calls.add === 1, "task create did not use calendar.addItem");

  const rereadCreatedTask = await api.getTask("cal-a", createdTask.id);
  assert(rereadCreatedTask.id === createdTask.id, "getTask did not read the created task");

  let updatedTask = await api.updateTask("cal-a", createdTask.id, {
    status: "IN-PROCESS",
    percentComplete: 37,
    priority: 1,
    due: "2026-10-06",
  });
  assert(updatedTask.status === "IN-PROCESS", "task status update failed");
  assert(updatedTask.percentComplete === 37, "task progress update failed");
  assert(updatedTask.priority === 1, "task priority update failed");
  assert(updatedTask.due.icalString === "20261006", "task due update failed");

  updatedTask = await api.updateTask("cal-a", createdTask.id, {
    percentComplete: 100,
  });
  assert(updatedTask.completed, "100 percent must complete task");
  assert(updatedTask.status === "COMPLETED", "100 percent must set COMPLETED");

  updatedTask = await api.updateTask("cal-a", createdTask.id, {
    status: null,
  });
  assert(updatedTask.status === "", "clearing status failed");
  assert(updatedTask.percentComplete === 0, "clearing status must reset progress");

  await assertRejects(
    () => api.updateTask("cal-a", createdTask.id, {status: "BROKEN"}),
    /Unsupported VTODO status/,
    "invalid status must be rejected"
  );
  await assertRejects(
    () => api.updateTask("cal-a", createdTask.id, {priority: 42}),
    /Priority must be/,
    "invalid priority must be rejected"
  );
  await assertRejects(
    () => api.updateTask("cal-a", createdTask.id, {percentComplete: 101}),
    /Percent complete/,
    "invalid percent must be rejected"
  );
  await assertRejects(
    () => api.createTask("cal-ro", {title: "blocked"}),
    /read-only/,
    "read-only calendar write must be rejected"
  );
  await assertRejects(
    () => api.createTask("cal-disabled", {title: "blocked"}),
    /disabled/,
    "disabled calendar write must be rejected"
  );
  await assertRejects(
    () => api.createTask("cal-events-only", {title: "blocked"}),
    /does not support tasks/,
    "task-unsupported calendar must be rejected"
  );
  await assertRejects(
    () => api.updateTask("cal-a", "missing", {title: "x"}),
    /not found/,
    "missing task must be rejected"
  );
  await assertRejects(
    () => api.createTask("cal-a", {title: "x", due: "not-a-date"}),
    /Unsupported date/,
    "invalid date must be rejected"
  );

  const createdEvent = await api.createEvent("cal-a", {
    title: "Meeting",
    start: "2026-10-05T09:00",
    end: "2026-10-05T10:30",
    categories: ["Work", "Work", "Meeting"],
    description: "real provider path",
  });
  assert(createdEvent.id, "created event has no UID");
  assert(createdEvent.start.icalString === "20261005T090000", "event start conversion failed");
  assert(createdEvent.end.icalString === "20261005T103000", "event end conversion failed");
  assert(createdEvent.categories.join(",") === "Work,Meeting", "event categories failed");
  const rereadCreatedEvent = await api.getEvent("cal-a", createdEvent.id);
  assert(rereadCreatedEvent.id === createdEvent.id, "getEvent did not read the created event");

  const openEvent = await api.createEvent("cal-a", {
    title: "Open-ended event",
    start: "2026-10-05T14:00",
    end: null,
  });
  assert(openEvent.id, "open-ended event has no UID");
  assert(openEvent.end === null, "open-ended event unexpectedly gained DTEND");

  let openEventRead = await api.getEvent("cal-a", openEvent.id);
  assert(openEventRead.end === null, "open-ended event read-back gained DTEND");
  await api.updateEvent("cal-a", openEvent.id, {
    end: "2026-10-05T14:30",
  });
  openEventRead = await api.getEvent("cal-a", openEvent.id);
  assert(openEventRead.end?.icalString === "20261005T143000", "ordinary VEVENT update failed");

  await assertRejects(
    () => api.createEvent("cal-a", {title: "No start"}),
    /Event start is required/,
    "event without start must fail"
  );
  await assertRejects(
    () => api.createEvent("cal-a", {
      title: "Backwards",
      start: "2026-10-05T11:00",
      end: "2026-10-05T10:00",
    }),
    /end must not be before/,
    "backwards event must fail"
  );
  await assertRejects(
    () => api.createEvent("cal-tasks-only", {
      title: "blocked",
      start: "2026-10-05T11:00",
    }),
    /does not support events/,
    "event-unsupported calendar must be rejected"
  );

  const ranged = await api.listEvents("cal-a", "2026-10-05", "2026-10-06");
  assert(ranged.some(x => x.id === createdEvent.id), "event range read failed");

  const updatedEvent = await api.updateEvent("cal-a", createdEvent.id, {
    title: "Meeting updated",
    start: "2026-10-05T12:00",
    end: "2026-10-05T13:00",
    categories: ["Updated"],
  });
  assert(updatedEvent.title === "Meeting updated", "event title update failed");
  assert(updatedEvent.start.icalString === "20261005T120000", "event start update failed");
  assert(updatedEvent.categories.join(",") === "Updated", "event category update failed");

  await assertRejects(
    () => api.updateEvent("cal-a", createdEvent.id, {
      start: "2026-10-05T14:00",
      end: "2026-10-05T13:00",
    }),
    /end must not be before/,
    "event update must reject backwards range"
  );

  const eventManager = api.onItemsChanged.__eventManager;
  let fired = 0;
  const unregister = eventManager.options.register({async() { fired++; }});
  assert(observer, "calendar observer was not registered");
  observer.onAddItem();
  observer.onModifyItem();
  observer.onDeleteItem();
  observer.onLoad();
  assert(fired === 4, "calendar change event did not fire for all supported changes");
  unregister();
  assert(observer === null, "calendar observer was not removed");

  const deletedTask = await api.deleteTask("cal-a", createdTask.id);
  const deletedEvent = await api.deleteEvent("cal-a", createdEvent.id);
  const deletedOpenEvent = await api.deleteEvent("cal-a", openWorkEvent.id);
  assert(deletedTask.ok && deletedEvent.ok && deletedOpenEvent.ok, "delete API result is wrong");
  assert(!(await calendarA.getItem(createdTask.id)), "task still exists after delete");
  assert(!(await calendarA.getItem(createdEvent.id)), "event still exists after delete");
  assert(!(await calendarA.getItem(openWorkEvent.id)), "open work event still exists after delete");
  assert(calendarA.calls.delete === 3, "deletes did not use calendar.deleteItem");

  assert(calendarA.calls.add === 3, "all creates must use Thunderbird calendar.addItem");
  assert(calendarA.calls.modify >= 4, "updates must use Thunderbird calendar.modifyItem");

  console.log("direct-caldav-api-harness: PASS");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
