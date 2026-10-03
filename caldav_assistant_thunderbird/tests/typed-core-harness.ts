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

console.log("typed-core-harness: PASS");
