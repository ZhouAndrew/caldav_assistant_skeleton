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

const completedRuntime = nextRuntime("complete", started, inProcess);
assert(completedRuntime.currentWorkId === null, "complete must clear currentWorkId");

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

console.log("typed-core-harness: PASS");
