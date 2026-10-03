import {TaskSnapshot} from "../src/domain";
import {
  getOpenSession,
  parseWorkDescription,
  serializeWorkDescription,
} from "../src/work-description";
import {makeTaskId, parseTaskId} from "../src/task-id";
import {planTaskAction} from "../src/workflow";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const roundTrip = parseTaskId(
  makeTaskId({calendarId: "cal A", uid: "uid/1", recurrenceId: "20261003T090000"})
);
assert(roundTrip?.calendarId === "cal A", "Task id calendar did not round-trip");
assert(roundTrip?.uid === "uid/1", "Task id uid did not round-trip");
assert(
  roundTrip?.recurrenceId === "20261003T090000",
  "Task id recurrence did not round-trip"
);

const base: TaskSnapshot = Object.freeze({
  calendarId: "cal A",
  uid: "uid/1",
  recurrenceId: "",
  title: "测试 Task",
  status: "NEEDS-ACTION",
  percentComplete: 35,
  description: "用户第一行\n用户第二行 😀",
});

const start = planTaskAction(
  "start",
  base,
  null,
  "2026-10-03T16:00:00+08:00",
  "session-1"
);
assert(start.ok, "Start should be accepted");
assert(start.taskPatch.status === "IN-PROCESS", "Start should set IN-PROCESS");
assert(start.nextCurrentWorkId === makeTaskId(base), "Start pointer is wrong");

const startedDescription = start.taskPatch.description;
const parsedStarted = parseWorkDescription(startedDescription);
assert(parsedStarted.ok, "Started Description should parse");
assert(
  parsedStarted.userText === base.description,
  "User Description text changed during Start"
);
const open = getOpenSession(parsedStarted);
assert(open?.id === "session-1", "Open session missing");
assert(open?.before.status === "NEEDS-ACTION", "Pre-Start status was not stored");
assert(open?.before.percentComplete === 35, "Pre-Start progress was not stored");
assert(
  serializeWorkDescription(parsedStarted) === startedDescription,
  "Description serialization is not idempotent"
);

const current: TaskSnapshot = Object.freeze({
  ...base,
  status: "IN-PROCESS",
  description: startedDescription,
});
const stop = planTaskAction(
  "stop",
  current,
  makeTaskId(current),
  "2026-10-03T16:30:00+08:00",
  "ignored"
);
assert(stop.ok, "Stop should be accepted");
assert(stop.taskPatch.status === "NEEDS-ACTION", "Stop did not restore status");
assert(stop.taskPatch.percentComplete === 35, "Stop did not restore progress");
assert(stop.nextCurrentWorkId === null, "Stop did not clear pointer");
assert(stop.closedSession?.result === "stop", "Stop did not close session");

const parsedStopped = parseWorkDescription(stop.taskPatch.description);
assert(parsedStopped.ok, "Stopped Description should parse");
assert(parsedStopped.userText === base.description, "Stop changed user Description");
assert(getOpenSession(parsedStopped) === null, "Stop left an open session");

const anotherTask: TaskSnapshot = Object.freeze({
  ...base,
  uid: "uid-2",
});
const blocked = planTaskAction(
  "start",
  anotherTask,
  makeTaskId(current),
  "2026-10-03T16:05:00+08:00",
  "session-2"
);
assert(!blocked.ok && blocked.reason === "current-work-exists", "Second Start must be rejected");

const notCurrent = planTaskAction(
  "complete",
  current,
  makeTaskId(anotherTask),
  "2026-10-03T16:10:00+08:00",
  "ignored"
);
assert(!notCurrent.ok && notCurrent.reason === "not-current", "Non-current Complete must be rejected");

const complete = planTaskAction(
  "complete",
  current,
  makeTaskId(current),
  "2026-10-03T16:45:00+08:00",
  "ignored"
);
assert(complete.ok, "Complete should be accepted");
assert(complete.taskPatch.status === "COMPLETED", "Complete status is wrong");
assert(complete.taskPatch.percentComplete === 100, "Complete progress is wrong");
assert(complete.closedSession?.result === "complete", "Complete did not close session");

const cancel = planTaskAction(
  "cancel",
  current,
  makeTaskId(current),
  "2026-10-03T16:50:00+08:00",
  "ignored"
);
assert(cancel.ok, "Cancel should be accepted");
assert(cancel.taskPatch.status === "CANCELLED", "Cancel status is wrong");
assert(cancel.closedSession?.result === "cancel", "Cancel did not close session");

const malformed: TaskSnapshot = Object.freeze({
  ...base,
  description: base.description + "\n\n[CALDAV-ASSISTANT-WORKLOG v1]\n{bad json}\n[/CALDAV-ASSISTANT-WORKLOG]",
});
const malformedResult = planTaskAction(
  "start",
  malformed,
  null,
  "2026-10-03T17:00:00+08:00",
  "session-x"
);
assert(
  !malformedResult.ok && malformedResult.reason === "description-corrupt",
  "Malformed Assistant block must block destructive writes"
);

const finished: TaskSnapshot = Object.freeze({
  ...base,
  status: "COMPLETED",
  percentComplete: 100,
});
const finishedStart = planTaskAction(
  "start",
  finished,
  null,
  "2026-10-03T17:00:00+08:00",
  "session-f"
);
assert(!finishedStart.ok && finishedStart.reason === "finished", "Finished Task must not start");


const noStatus: TaskSnapshot = Object.freeze({
  ...base,
  uid: "uid-no-status",
  status: "",
  percentComplete: 0,
  description: "没有显式 STATUS",
});
const noStatusStart = planTaskAction(
  "start",
  noStatus,
  null,
  "2026-10-03T18:00:00+08:00",
  "session-no-status"
);
assert(noStatusStart.ok, "Task without STATUS should start");
const noStatusCurrent: TaskSnapshot = Object.freeze({
  ...noStatus,
  status: "IN-PROCESS",
  description: noStatusStart.taskPatch.description,
});
const noStatusStop = planTaskAction(
  "stop",
  noStatusCurrent,
  makeTaskId(noStatusCurrent),
  "2026-10-03T18:05:00+08:00",
  "ignored"
);
assert(noStatusStop.ok, "Task without original STATUS should stop");
assert(
  noStatusStop.taskPatch.status === "",
  "Stop must restore absence of STATUS exactly"
);

console.log("cleanroom core-harness: PASS");
