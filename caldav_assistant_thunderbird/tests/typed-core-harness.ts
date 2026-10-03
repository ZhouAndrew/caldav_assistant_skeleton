import {
  AssistantRuntime,
  TaskSnapshot,
  makeWorkTaskId,
  parseWorkTaskId,
  taskRef,
} from "../src/domain";
import {
  actionAllowed,
  deriveWorkState,
  nextRuntime,
} from "../src/functional-core";
import {
  currentWorkIdFromLegacyRuntime,
  normalizeRuntime,
} from "../src/legacy-runtime";
import {
  fallbackRestoreSnapshot,
  restoreSnapshotFromStartReceipt,
} from "../src/restore-snapshot";
import {
  deriveWorkTiming,
  elapsedWorkMs,
} from "../src/work-timing";
import {planWorkAction} from "../src/action-plan";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const ref = taskRef("tasks", "uid-1", "20261003T090000");
const workTaskId = makeWorkTaskId(ref);
const parsed = parseWorkTaskId(workTaskId);
assert(parsed?.calendarId === ref.calendarId, "calendar id did not round-trip");
assert(parsed?.id === ref.id, "task uid did not round-trip");
assert(parsed?.recurrenceId === ref.recurrenceId, "recurrence id did not round-trip");

const task: TaskSnapshot = Object.freeze({
  ...ref,
  workTaskId,
  title: "Typed core acceptance",
  status: "NEEDS-ACTION",
  paused: false,
  percentComplete: 0,
});

const idle: AssistantRuntime = Object.freeze({currentWorkId: null});
assert(actionAllowed("start", idle, task), "idle task should be startable");

const startPlan = planWorkAction("start", idle, task);
assert(startPlan.ok, "start plan was rejected");
assert(startPlan.taskChanges.status === "IN-PROCESS", "start plan status is wrong");
assert(startPlan.taskChanges.paused === false, "start plan pause flag is wrong");
assert(startPlan.nextCurrentWorkId === workTaskId, "start plan pointer is wrong");
assert(startPlan.historyEffect === "open", "start plan history effect is wrong");

const started = nextRuntime("start", idle, task);
assert(started.currentWorkId === workTaskId, "start must set only currentWorkId");

const inProcess: TaskSnapshot = Object.freeze({
  ...task,
  status: "IN-PROCESS",
});
assert(deriveWorkState(started, inProcess) === "working", "work state should be derived");

const paused: TaskSnapshot = Object.freeze({
  ...inProcess,
  paused: true,
});
assert(deriveWorkState(started, paused) === "paused", "pause state should come from VTODO");
assert(actionAllowed("resume", started, paused), "paused current task should be resumable");

const pausePlan = planWorkAction("pause", started, inProcess);
assert(pausePlan.ok, "pause plan was rejected");
assert(pausePlan.taskChanges.paused === true, "pause plan did not set paused");
assert(pausePlan.nextCurrentWorkId === workTaskId, "pause plan changed pointer");
assert(pausePlan.historyEffect === "close", "pause plan should close history");

const resumePlan = planWorkAction("resume", started, paused);
assert(resumePlan.ok, "resume plan was rejected");
assert(resumePlan.taskChanges.paused === false, "resume plan did not clear paused");
assert(resumePlan.nextCurrentWorkId === workTaskId, "resume plan changed pointer");
assert(resumePlan.historyEffect === "open", "resume plan should open history");

const impossiblePause = planWorkAction("pause", started, task);
assert(!impossiblePause.ok, "pause plan accepted a non-IN-PROCESS task");
assert(impossiblePause.reason === "not-working", "pause rejection reason is wrong");

const completedRuntime = nextRuntime("complete", started, inProcess);
assert(completedRuntime.currentWorkId === null, "complete must clear currentWorkId");

const completePlan = planWorkAction("complete", started, inProcess);
assert(completePlan.ok, "complete plan was rejected");
assert(completePlan.taskChanges.status === "COMPLETED", "complete plan status is wrong");
assert(completePlan.taskChanges.percentComplete === 100, "complete plan lost 100 percent");
assert(completePlan.nextCurrentWorkId === null, "complete plan did not clear pointer");
assert(completePlan.historyEffect === "close", "complete plan should close history");

const cancelPlan = planWorkAction("cancel", started, inProcess);
assert(cancelPlan.ok, "cancel plan was rejected");
assert(cancelPlan.taskChanges.status === "CANCELLED", "cancel plan status is wrong");
assert(cancelPlan.nextCurrentWorkId === null, "cancel plan did not clear pointer");

const finished: TaskSnapshot = Object.freeze({
  ...inProcess,
  status: "COMPLETED",
  percentComplete: 100,
});
assert(!actionAllowed("start", idle, finished), "completed task must not be startable");

const migrated = currentWorkIdFromLegacyRuntime({
  state: "working",
  currentTask: {
    calendarId: "tasks",
    id: "uid-1",
    recurrenceId: "20261003T090000",
  },
});
assert(migrated === workTaskId, "legacy recurring task identity did not migrate safely");

const normalizedFromLegacy = normalizeRuntime(null, {
  state: "paused",
  currentTask: {
    calendarId: "tasks",
    id: "uid-1",
    recurrenceId: "20261003T090000",
  },
  currentWorkEvent: {id: "obsolete-work-event"},
  accumulatedMs: 12345,
});
assert(
  normalizedFromLegacy.currentWorkId === workTaskId,
  "legacy runtime did not collapse to one currentWorkId"
);

const explicit = normalizeRuntime(workTaskId, {
  currentTask: {calendarId: "wrong", id: "wrong", recurrenceId: ""},
});
assert(explicit.currentWorkId === workTaskId, "valid new runtime must win over legacy data");

const invalidExplicit = normalizeRuntime("not-a-valid-work-task-id", {
  currentTask: {
    calendarId: "tasks",
    id: "uid-1",
    recurrenceId: "20261003T090000",
  },
});
assert(
  invalidExplicit.currentWorkId === workTaskId,
  "invalid new runtime should recover from legacy runtime"
);

const restored = restoreSnapshotFromStartReceipt(inProcess, {
  workTaskId,
  beforeStatus: "NEEDS-ACTION",
  beforePaused: false,
  beforePercentComplete: 35,
});
assert(restored?.status === "NEEDS-ACTION", "history restore lost original status");
assert(restored?.paused === false, "history restore invented pause state");
assert(restored?.percentComplete === 35, "history restore lost original progress");

const switchPlan = planWorkAction("switch-away", started, inProcess, restored);
assert(switchPlan.ok, "switch-away plan was rejected");
assert(switchPlan.taskChanges.status === "NEEDS-ACTION", "switch plan lost restore status");
assert(switchPlan.taskChanges.percentComplete === 35, "switch plan lost restore progress");
assert(switchPlan.nextCurrentWorkId === null, "switch plan did not clear pointer");
assert(switchPlan.historyEffect === "close", "switch plan should close history");

const missingRestorePlan = planWorkAction("switch-away", started, inProcess);
assert(!missingRestorePlan.ok, "switch-away accepted without a restore snapshot");
assert(missingRestorePlan.reason === "restore-required", "missing restore reason is wrong");

const wrongHistory = restoreSnapshotFromStartReceipt(inProcess, {
  workTaskId: makeWorkTaskId(taskRef("tasks", "different", "")),
  beforeStatus: "NEEDS-ACTION",
  beforePaused: false,
  beforePercentComplete: 5,
});
assert(wrongHistory === null, "restore accepted history for another Task");

const conservative = fallbackRestoreSnapshot({
  ...inProcess,
  percentComplete: 42,
});
assert(conservative.status === "NEEDS-ACTION", "fallback must remain incomplete");
assert(conservative.paused === false, "fallback must release Assistant pause state");
assert(conservative.percentComplete === 42, "fallback should preserve existing progress");

const timing = deriveWorkTiming([
  {action: "start", success: true, timestampMs: 1000},
  {action: "pause", success: true, timestampMs: 6000},
  {action: "resume", success: true, timestampMs: 10000},
]);
assert(timing.accumulatedMs === 5000, "audit timing lost the first work segment");
assert(timing.runningSinceMs === 10000, "audit timing did not keep resumed segment open");
assert(elapsedWorkMs(timing, 16000) === 11000, "live elapsed timing is wrong");

const closedTiming = deriveWorkTiming([
  {action: "start", success: true, timestampMs: 1000},
  {action: "pause", success: true, timestampMs: 4000},
  {action: "resume", success: true, timestampMs: 7000},
  {action: "switch-away", success: true, timestampMs: 9000},
]);
assert(closedTiming.accumulatedMs === 5000, "closed timing lost accumulated work");
assert(closedTiming.runningSinceMs === null, "closed timing left a segment running");

const failedActionsIgnored = deriveWorkTiming([
  {action: "start", success: true, timestampMs: 1000},
  {action: "pause", success: false, timestampMs: 2000},
]);
assert(
  elapsedWorkMs(failedActionsIgnored, 4000) === 3000,
  "failed history entry changed timing"
);

console.log("typed-core-harness: PASS");
