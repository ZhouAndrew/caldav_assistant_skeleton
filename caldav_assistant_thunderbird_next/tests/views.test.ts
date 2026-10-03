import {TaskSnapshot} from "../src/domain";
import {encodeTaskId} from "../src/task-id";
import {planTaskAction} from "../src/workflow";
import {deriveLogsView} from "../src/views/logs";
import {deriveTaskPageView} from "../src/views/task-page";
import {deriveTaskPickerView} from "../src/views/task-picker";
import {deriveTodayView} from "../src/views/today";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function task(uid: string): TaskSnapshot {
  const identity = {calendarId: "tasks", uid, recurrenceId: ""};
  return Object.freeze({
    ...identity,
    taskId: encodeTaskId(identity),
    title: uid,
    description: "用户说明",
    status: "NEEDS-ACTION",
    percentComplete: 10,
  });
}

const a = task("A");
const start = planTaskAction(
  "start",
  a,
  null,
  "2026-10-03T23:55:00+08:00",
  "session-A"
);
assert(start.ok, "fixture Start failed");
const active: TaskSnapshot = Object.freeze({
  ...a,
  description: start.taskPatch.description,
  status: start.taskPatch.status,
  percentComplete: start.taskPatch.percentComplete,
});

const activeView = deriveTaskPageView(
  active,
  active.taskId,
  "2026-10-04T00:05:00+08:00"
);
assert(activeView.isCurrent, "current Task page lost current identity");
assert(
  activeView.actions.join(",") === "stop,complete,cancel",
  "current Task page exposed wrong actions"
);
assert(activeView.elapsedMs === 10 * 60 * 1000, "elapsed time is wrong");
assert(activeView.userDescription === "用户说明", "Assistant block leaked into user text");

const otherCurrent = deriveTaskPageView(
  task("B"),
  active.taskId,
  "2026-10-04T00:05:00+08:00"
);
assert(otherCurrent.actions.length === 0, "non-current Task exposed Start");
assert(
  otherCurrent.noticeKey === "anotherTaskActive",
  "non-current Task conflict is not visible"
);

const stale = deriveTaskPageView(
  task("stale"),
  task("stale").taskId,
  "2026-10-04T00:05:00+08:00"
);
assert(stale.actions.length === 0, "stale pointer exposed workflow action");
assert(Boolean(stale.errorKey), "stale pointer did not request recovery");

const idle = deriveTaskPageView(
  task("idle"),
  null,
  "2026-10-04T00:05:00+08:00"
);
assert(idle.actions.join(",") === "start", "idle Task did not expose Start");

const picker = deriveTaskPickerView(
  {
    filter: "notstarted",
    search: "math",
    calendarIds: ["tasks"],
  },
  [
    {
      taskId: "1",
      calendarId: "tasks",
      calendarName: "Tasks",
      title: "English",
      due: null,
      categories: [],
    },
    {
      taskId: "2",
      calendarId: "tasks",
      calendarName: "Tasks",
      title: "Math question",
      due: "2026-10-04",
      categories: ["study"],
    },
  ]
);
assert(picker.filter === "notstarted", "Picker lost Thunderbird filter identity");
assert(picker.items.length === 1, "Picker text search is wrong");
assert(picker.items[0]?.taskId === "2", "Picker returned wrong Task");

// The Picker has no workflow input. An active Task may be absent from this source
// without changing any workflow decision; the Task Page remains authoritative.
const filteredAwayPicker = deriveTaskPickerView(
  {filter: "notstarted", search: "", calendarIds: ["tasks"]},
  [{
    taskId: "B",
    calendarId: "tasks",
    calendarName: "Tasks",
    title: "Other task",
    due: null,
    categories: [],
  }]
);
assert(
  filteredAwayPicker.items.every(item => item.taskId !== active.taskId),
  "fixture did not filter away active Task"
);
const stillActive = deriveTaskPageView(
  active,
  active.taskId,
  "2026-10-04T00:05:00+08:00"
);
assert(
  stillActive.actions.includes("stop"),
  "Picker visibility incorrectly changed Task workflow state"
);

const todayOct3 = deriveTodayView([active], "2026-10-03");
assert(todayOct3.rows.length === 1, "Today projection lost session start date");
const todayOct4 = deriveTodayView([active], "2026-10-04");
assert(
  todayOct4.rows.length === 0,
  "Today projection used runner timezone instead of stored timestamp date"
);

const logsInput = Object.freeze([
  Object.freeze({
    timestamp: "2026-10-03T12:00:00Z",
    scope: "workflow",
    success: true,
    summary: "Start A",
  }),
  Object.freeze({
    timestamp: "2026-10-03T13:00:00Z",
    scope: "wordpress",
    success: false,
    summary: "HTTP 401",
  }),
]);
const logs = deriveLogsView(logsInput, {
  date: "2026-10-03",
  scope: "wordpress",
  search: "401",
});
assert(logs.records.length === 1, "Logs view filter is wrong");
assert(logsInput.length === 2, "Logs view mutated source");

console.log("clean-room views: PASS");
