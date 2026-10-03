"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function createTodo(calendar, {
  uid = "uid-1",
  recurrenceId = "",
  title = "Task",
  description = "Description",
  status = "NEEDS-ACTION",
  percentComplete = 25,
  due = null,
  categories = [],
} = {}) {
  const item = {
    id: uid,
    calendar,
    recurrenceId: recurrenceId ? {icalString: recurrenceId} : null,
    title,
    descriptionText: description,
    status,
    percentComplete,
    dueDate: due ? {value: due} : null,
    completedDate: null,
    getCategories() {
      return [...categories];
    },
    isTodo() {
      return true;
    },
    clone() {
      const clone = createTodo(calendar, {
        uid: this.id,
        recurrenceId: this.recurrenceId?.icalString || "",
        title: this.title,
        description: this.descriptionText,
        status: this.status,
        percentComplete: this.percentComplete,
        due: this.dueDate?.value || null,
        categories: this.getCategories(),
      });
      clone.completedDate = this.completedDate;
      return clone;
    },
  };

  Object.defineProperty(item, "isCompleted", {
    get() {
      return Boolean(this.completedDate) ||
        this.percentComplete === 100 ||
        this.status === "COMPLETED";
    },
    set(value) {
      if (value) {
        this.completedDate = {icalString: "20261003T120000Z"};
        this.status = "COMPLETED";
        this.percentComplete = 100;
      } else {
        this.completedDate = null;
        this.status = "";
        this.percentComplete = 0;
      }
    },
  });
  return item;
}

const calendar = {
  id: "cal-1",
  name: "Tasks",
  master: null,
  queryItems: [],
  lastModify: null,
  getProperty(name) {
    if (name === "capabilities.tasks.supported") return true;
    if (name === "disabled") return false;
    if (name === "calendar-main-in-composite") return true;
    return null;
  },
  async getItemsAsArray() {
    return this.master ? [this.master] : [];
  },
  async getItem(uid) {
    return this.master?.id === uid ? this.master : null;
  },
  async modifyItem(next, old) {
    this.lastModify = {next, old};
    return next;
  },
};

const occurrence = createTodo(calendar, {
  uid: "uid-1",
  recurrenceId: "20261003T090000",
  title: "Occurrence",
  description: "Occurrence description",
  status: "NEEDS-ACTION",
  percentComplete: 35,
  due: "20261004T120000",
  categories: ["study"],
});
const master = createTodo(calendar, {
  uid: "uid-1",
  title: "Master",
  description: "Master description",
});
master.recurrenceInfo = {
  getExceptionIds() {
    return [{icalString: "20261003T090000"}];
  },
  getExceptionFor(value) {
    return value.icalString === "20261003T090000" ? occurrence : null;
  },
  getOccurrenceFor(value) {
    assert(
      value.icalString === "20261003T090000",
      "recurrence id was not passed through cal.createDateTime"
    );
    return occurrence;
  },
};
calendar.master = master;
calendar.queryItems = [master, occurrence];

const filterCalls = [];
class FakeCalFilter {
  constructor() {
    this.itemType = 0;
    this.selectedDate = null;
    this.filterText = "";
    this.filterName = "";
  }
  applyFilter(name) {
    this.filterName = name;
    filterCalls.push({type: "apply", name, text: this.filterText});
  }
  getItems(targetCalendar) {
    filterCalls.push({
      type: "getItems",
      calendarId: targetCalendar.id,
      name: this.filterName,
      text: this.filterText,
    });
    return targetCalendar.queryItems || [];
  }
}

const Services = {
  scriptloader: {
    loadSubScript(uri, scope) {
      assert(
        uri === "chrome://calendar/content/widgets/calendar-filter.js",
        "unexpected Thunderbird filter script"
      );
      scope.calFilter = FakeCalFilter;
    },
  },
};

const cal = {
  manager: {
    getCalendarById(id) {
      return id === calendar.id ? calendar : null;
    },
    getCalendars() {
      return [calendar];
    },
  },
  createDateTime(value) {
    return {icalString: String(value)};
  },
  dtz: {
    now() {
      return {icalString: "20261003T120000"};
    },
    toRFC3339(value) {
      return value?.value ? "2026-10-04T12:00:00+08:00" : null;
    },
  },
  iterate: {
    async streamToArray(stream) {
      return [...stream];
    },
  },
};

class ExtensionAPI {}

const context = {
  Ci: {
    calICalendar: {
      ITEM_FILTER_COMPLETED_YES: 1 << 0,
      ITEM_FILTER_COMPLETED_NO: 1 << 1,
      ITEM_FILTER_COMPLETED_ALL: (1 << 0) | (1 << 1),
      ITEM_FILTER_TYPE_TODO: 1 << 2,
    },
  },
  ChromeUtils: {
    importESModule(uri) {
      if (uri.includes("ExtensionCommon")) {
        return {ExtensionCommon: {ExtensionAPI}};
      }
      if (uri.includes("calUtils")) {
        return {cal};
      }
      if (uri.includes("Services.sys.mjs")) {
        return {Services};
      }
      throw new Error("Unexpected module: " + uri);
    },
  },
  console,
  Set,
  Error,
  String,
  Number,
};
vm.createContext(context);

const implPath = path.join(
  __dirname,
  "..",
  "addon",
  "api",
  "NativeTasks",
  "implementation.js"
);
vm.runInContext(fs.readFileSync(implPath, "utf8"), context, {
  filename: implPath,
});

async function main() {
  const api = new context.NativeTasks().getAPI().NativeTasks;


  const query = await api.queryTasks({
    filter: "open",
    search: "study",
    calendarIds: ["cal-1"],
  });
  assert(query.complete === true, "native Task query unexpectedly incomplete");
  assert(query.failures.length === 0, "native Task query reported false failure");
  assert(query.tasks.length === 2, "native Task query lost filtered items");
  assert(
    filterCalls.some(call =>
      call.type === "apply" &&
      call.name === "open"
    ),
    "Thunderbird filter name was not applied"
  );
  assert(
    filterCalls.some(call =>
      call.type === "getItems" &&
      call.calendarId === "cal-1" &&
      call.text === "study"
    ),
    "Thunderbird filterText/search was not passed to calFilter"
  );
  const queriedOccurrence = query.tasks.find(
    item => item.recurrenceId === "20261003T090000"
  );
  assert(queriedOccurrence, "native query lost recurring occurrence identity");
  assert(queriedOccurrence.status === "NEEDS-ACTION", "native query lost status");
  assert(queriedOccurrence.percentComplete === 35, "native query lost progress");
  assert(
    queriedOccurrence.due === "2026-10-04T12:00:00+08:00",
    "native query lost due date"
  );
  assert(
    queriedOccurrence.categories[0] === "study",
    "native query lost categories"
  );

  const masterView = await api.getTask("cal-1", "uid-1", "");
  assert(masterView.title === "Master", "master VTODO read failed");
  assert(masterView.description === "Master description", "master DESCRIPTION lost");

  const occurrenceView = await api.getTask(
    "cal-1",
    "uid-1",
    "20261003T090000"
  );
  assert(occurrenceView.title === "Occurrence", "recurring occurrence was not resolved");
  assert(occurrenceView.percentComplete === 35, "occurrence progress lost");

  const updated = await api.updateTask(
    "cal-1",
    "uid-1",
    "20261003T090000",
    {
      description: "Updated description",
      status: "IN-PROCESS",
      percentComplete: 35,
    }
  );
  assert(calendar.lastModify?.old === occurrence, "modifyItem oldItem was not occurrence");
  assert(calendar.lastModify?.next !== occurrence, "VTODO was mutated without clone");
  assert(updated.description === "Updated description", "DESCRIPTION update failed");
  assert(updated.status === "IN-PROCESS", "STATUS update failed");
  assert(updated.percentComplete === 35, "PERCENT update failed");
  assert(
    occurrence.descriptionText === "Occurrence description",
    "old immutable view was mutated"
  );

  const completed = await api.updateTask(
    "cal-1",
    "uid-1",
    "20261003T090000",
    {
      description: "Done",
      status: "COMPLETED",
      percentComplete: 100,
    }
  );
  assert(completed.status === "COMPLETED", "Thunderbird completion semantics not used");
  assert(completed.percentComplete === 100, "completion percent wrong");

  let invalidRejected = false;
  try {
    await api.updateTask(
      "cal-1",
      "uid-1",
      "20261003T090000",
      {
        description: "Invalid",
        status: "IN-PROCESS",
        percentComplete: 100,
      }
    );
  } catch {
    invalidRejected = true;
  }
  assert(invalidRejected, "non-completed 100% VTODO was accepted");

  const scan = await api.scanStoredTasks();
  assert(scan.complete === true, "stored task scan unexpectedly incomplete");
  assert(scan.failures.length === 0, "stored task scan reported a false failure");
  assert(scan.tasks.length === 2, "stored task scan must include master + exception");
  assert(
    scan.tasks.some(item =>
      item.uid === "uid-1" &&
      item.recurrenceId === "20261003T090000"
    ),
    "stored recurring exception was omitted from scan"
  );

  const failingCalendar = {
    id: "broken-cal",
    getProperty() {
      return true;
    },
    async getItemsAsArray() {
      throw new Error("provider read failed");
    },
  };
  cal.manager.getCalendars = () => [calendar, failingCalendar];

  const partial = await api.scanStoredTasks();
  assert(partial.complete === false, "partial scan was marked complete");
  assert(partial.tasks.length === 2, "healthy calendar Tasks were lost on partial scan");
  assert(partial.failures.length === 1, "provider failure was not surfaced");
  assert(
    partial.failures[0].calendarId === "broken-cal",
    "scan failure lost calendar identity"
  );

  console.log("native-tasks harness: PASS");
}

main().catch(error => {
  console.error(error);
  throw error;
});
