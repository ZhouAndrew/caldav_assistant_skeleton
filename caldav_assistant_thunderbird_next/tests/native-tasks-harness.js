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
} = {}) {
  const item = {
    id: uid,
    calendar,
    recurrenceId: recurrenceId ? {icalString: recurrenceId} : null,
    title,
    descriptionText: description,
    status,
    percentComplete,
    completedDate: null,
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
  master: null,
  lastModify: null,
  getProperty(name) {
    if (name === "capabilities.tasks.supported") return true;
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
