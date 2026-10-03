import {TaskSnapshot} from "../src/domain.js";
import {
  deriveTaskPageModel,
  deriveTaskPickerModel,
} from "../src/page-models.js";
import {migrateLegacySettings} from "../src/settings-migration.js";
import {makeTaskId} from "../src/task-id.js";
import {planTaskAction} from "../src/workflow.js";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const settings = migrateLegacySettings({
  taskView: "incomplete",
}).settings;

const a: TaskSnapshot = Object.freeze({
  calendarId: "cal",
  uid: "a",
  recurrenceId: "",
  title: "Alpha",
  status: "NEEDS-ACTION",
  percentComplete: 10,
  description: "用户 Alpha 描述",
});
const b: TaskSnapshot = Object.freeze({
  ...a,
  uid: "b",
  title: "Beta",
  status: "COMPLETED",
  percentComplete: 100,
});

const picker = deriveTaskPickerModel(settings, [a, b]);
assert(picker.items.length === 1, "Incomplete picker filter is wrong");
assert(picker.items[0]?.taskId === makeTaskId(a), "Picker returned wrong task");
assert(
  deriveTaskPickerModel(settings, [a, b], "alpha").items.length === 1,
  "Picker title search failed"
);
assert(
  deriveTaskPickerModel(settings, [a, b], "用户").items.length === 1,
  "Picker Description search failed"
);

const idle = deriveTaskPageModel(a, null, "2026-10-03T20:00:00+08:00");
assert(
  JSON.stringify(idle.actions) === JSON.stringify(["start"]),
  "Idle Task page must offer Start"
);

const startedPlan = planTaskAction(
  "start",
  a,
  null,
  "2026-10-03T19:00:00+08:00",
  "session-page"
);
assert(startedPlan.ok, "Page fixture Start failed");
const started: TaskSnapshot = Object.freeze({
  ...a,
  status: "IN-PROCESS",
  description: startedPlan.taskPatch.description,
});
const current = deriveTaskPageModel(
  started,
  makeTaskId(started),
  "2026-10-03T20:00:00+08:00"
);
assert(
  JSON.stringify(current.actions) ===
    JSON.stringify(["stop", "complete", "cancel"]),
  "Current Task page actions are wrong"
);
assert(current.elapsedMs === 60 * 60 * 1000, "Description timing is wrong");

const conflict = deriveTaskPageModel(
  a,
  makeTaskId({...a, uid: "other"}),
  "2026-10-03T20:00:00+08:00"
);
assert(conflict.actions.length === 0, "Conflicting Task must not offer Start");
assert(conflict.currentConflict, "Conflict state was not exposed");

const corrupt: TaskSnapshot = Object.freeze({
  ...a,
  description:
    "用户原文\n\n[CALDAV-ASSISTANT-WORKLOG v1]\n{bad}\n[/CALDAV-ASSISTANT-WORKLOG]",
});
const protectedModel = deriveTaskPageModel(
  corrupt,
  null,
  "2026-10-03T20:00:00+08:00"
);
assert(protectedModel.actions.length === 0, "Corrupt Description must block actions");
assert(protectedModel.workLogCorrupt, "Corrupt Description was not surfaced");

console.log("page-models-harness: PASS");
