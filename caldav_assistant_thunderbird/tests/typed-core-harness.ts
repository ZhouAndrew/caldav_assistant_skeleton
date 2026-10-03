import {
  AssistantRuntime,
  TaskSnapshot,
  makeWorkTaskId,
  parseWorkTaskId,
  taskRef,
} from "../src/domain";
import {
  actionAllowed,
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
  percentComplete: 35,
});

const idle: AssistantRuntime = Object.freeze({currentWorkId: null});
assert(actionAllowed("start", idle, task), "idle task should be startable");

const startPlan = planWorkAction("start", idle, task);
assert(startPlan.ok, "start plan was rejected");
assert(startPlan.taskChanges.status === "IN-PROCESS", "start plan status is wrong");
assert(startPlan.taskChanges.paused === false, "start must normalize legacy pause marker off");
assert(startPlan.nextCurrentWorkId === workTaskId, "start plan pointer is wrong");
assert(startPlan.historyEffect === "open", "start plan history effect is wrong");

const started = nextRuntime("start", idle, task);
assert(started.currentWorkId === workTaskId, "start must set only currentWorkId");

const inProcess: TaskSnapshot = Object.freeze({
  ...task,
  status: "IN-PROCESS",
  paused: false,
});
assert(actionAllowed("stop", started, inProcess), "current task should be stoppable");
assert(actionAllowed("complete", started, inProcess), "current task should be completable");
assert(actionAllowed("cancel", started, inProcess), "current task should be cancellable");

const restored = restoreSnapshotFromStartReceipt(inProcess, {
  workTaskId,
  beforeStatus: "NEEDS-ACTION",
  beforePaused: true,
  beforePercentComplete: 35,
});
assert(restored?.status === "NEEDS-ACTION", "history restore lost original status");
assert(restored?.paused === true, "legacy history pause marker was not readable");
assert(restored?.percentComplete === 35, "history restore lost original progress");

const stopPlan = planWorkAction("stop", started, inProcess, restored);
assert(stopPlan.ok, "stop plan was rejected");
assert(stopPlan.taskChanges.status === "NEEDS-ACTION", "stop plan lost restore status");
assert(stopPlan.taskChanges.paused === false, "stop resurrected legacy paused lifecycle");
assert(stopPlan.taskChanges.percentComplete === 35, "stop plan lost restore progress");
assert(stopPlan.nextCurrentWorkId === null, "stop plan did not clear pointer");
assert(stopPlan.historyEffect === "close", "stop plan should close history");

const stoppedRuntime = nextRuntime("stop", started, inProcess);
assert(stoppedRuntime.currentWorkId === null, "stop must clear currentWorkId");

const missingRestorePlan = planWorkAction("stop", started, inProcess);
assert(!missingRestorePlan.ok, "stop accepted without a restore snapshot");
assert(missingRestorePlan.reason === "restore-required", "missing restore reason is wrong");

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
assert(conservative.paused === false, "fallback must normalize old pause marker off");
assert(conservative.percentComplete === 42, "fallback should preserve existing progress");

const timing = deriveWorkTiming([
  {action: "start", success: true, timestampMs: 1000},
  {action: "stop", success: true, timestampMs: 6000},
]);
assert(timing.accumulatedMs === 5000, "Start/Stop timing lost work duration");
assert(timing.runningSinceMs === null, "Stop timing left a segment running");
assert(elapsedWorkMs(timing, 16000) === 5000, "stopped elapsed timing is wrong");

const legacyTiming = deriveWorkTiming([
  {action: "start", success: true, timestampMs: 1000},
  {action: "pause", success: true, timestampMs: 4000},
  {action: "resume", success: true, timestampMs: 7000},
  {action: "switch-away", success: true, timestampMs: 9000},
]);
assert(legacyTiming.accumulatedMs === 5000, "legacy immutable timing was not preserved");
assert(legacyTiming.runningSinceMs === null, "legacy closed timing left a segment running");

const failedActionsIgnored = deriveWorkTiming([
  {action: "start", success: true, timestampMs: 1000},
  {action: "stop", success: false, timestampMs: 2000},
]);
assert(
  elapsedWorkMs(failedActionsIgnored, 4000) === 3000,
  "failed history entry changed timing"
);

console.log("typed-core-harness: PASS");
