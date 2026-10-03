import {
  TaskSnapshot,
  parseTaskId,
  taskId,
} from "../src/domain";
import {
  closeSession,
  parseWorkDescription,
  serializeWorkDescription,
} from "../src/work-description";
import {deriveTaskPage, planTaskAction} from "../src/workflow";
import {
  migrateLegacySettings,
  redactSettingsForDiagnostics,
} from "../src/settings";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const base: TaskSnapshot = Object.freeze({
  calendarId: "calendar A",
  uid: "uid:1",
  recurrenceId: "",
  title: "测试 Task",
  status: "NEEDS-ACTION",
  completed: false,
  percentComplete: 35,
  description: "用户原文\n第二行 😀",
});

const id = taskId(base);
const roundTrip = parseTaskId(id);
assert(roundTrip?.calendarId === base.calendarId, "task id calendar failed");
assert(roundTrip?.uid === base.uid, "task id uid failed");
assert(roundTrip?.recurrenceId === "", "task id recurrence failed");

const start = planTaskAction({
  intent: "start",
  task: base,
  currentWorkId: null,
  now: "2026-10-03T16:00:00+08:00",
  sessionId: "session-1",
});
assert(start.ok, "start rejected");
assert(start.nextCurrentWorkId === id, "start pointer wrong");
const reservedStart = planTaskAction({
  intent: "start",
  task: base,
  currentWorkId: id,
  now: "2026-10-03T16:00:00+08:00",
  sessionId: "session-reserved",
});
assert(reservedStart.ok, "reserved Start pointer could not finish VTODO write");
assert(start.taskPatch.status === "IN-PROCESS", "start status wrong");
assert(typeof start.taskPatch.description === "string", "start missing description");

const started: TaskSnapshot = Object.freeze({
  ...base,
  status: "IN-PROCESS",
  description: String(start.taskPatch.description),
});

const parsedStarted = parseWorkDescription(started.description);
assert(parsedStarted.ok, "started description not parseable");
assert(
  parsedStarted.value.prefix === base.description + "\n\n",
  "user description prefix changed",
);
assert(parsedStarted.value.sessions.length === 1, "session not appended");
assert(parsedStarted.value.sessions[0]?.end === null, "new session already closed");

const stop = planTaskAction({
  intent: "stop",
  task: started,
  currentWorkId: id,
  now: "2026-10-03T16:30:00+08:00",
});
assert(stop.ok, "stop rejected");
assert(stop.taskPatch.status === "NEEDS-ACTION", "stop did not restore status");
assert(!("percentComplete" in stop.taskPatch), "stop must not roll progress back");
assert(stop.nextCurrentWorkId === null, "stop did not clear pointer");
assert(stop.closedSession?.result === "stop", "stop did not emit closed session");

const stoppedParsed = parseWorkDescription(String(stop.taskPatch.description));
assert(stoppedParsed.ok, "stopped description invalid");
assert(stoppedParsed.value.sessions[0]?.end !== null, "stop left open session");

const complete = planTaskAction({
  intent: "complete",
  task: started,
  currentWorkId: id,
  now: "2026-10-03T16:31:00+08:00",
});
assert(complete.ok, "complete rejected");
assert(complete.taskPatch.status === "COMPLETED", "complete status wrong");
assert(complete.taskPatch.percentComplete === 100, "complete percent wrong");

const cancel = planTaskAction({
  intent: "cancel",
  task: started,
  currentWorkId: id,
  now: "2026-10-03T16:32:00+08:00",
});
assert(cancel.ok, "cancel rejected");
assert(cancel.taskPatch.status === "CANCELLED", "cancel status wrong");
assert(!("percentComplete" in cancel.taskPatch), "cancel must not rewrite progress");

const conflict = planTaskAction({
  intent: "start",
  task: base,
  currentWorkId: JSON.stringify(["other", "uid", ""]),
  now: "2026-10-03T16:00:00+08:00",
  sessionId: "session-2",
});
assert(!conflict.ok && conflict.reason === "current-work-exists", "conflict start accepted");

const currentView = deriveTaskPage({task: started, currentWorkId: id});
assert(
  currentView.actions.join(",") === "stop,complete,cancel",
  "current page actions wrong",
);

const otherView = deriveTaskPage({
  task: base,
  currentWorkId: JSON.stringify(["other", "uid", ""]),
});
assert(otherView.actions.length === 0, "non-current page offered Start");
assert(otherView.anotherTaskIsCurrent, "current-task conflict not exposed");


const noStatus: TaskSnapshot = Object.freeze({
  ...base,
  uid: "uid-no-status",
  status: null,
  percentComplete: 42,
});
const noStatusId = taskId(noStatus);
const noStatusStart = planTaskAction({
  intent: "start",
  task: noStatus,
  currentWorkId: null,
  now: "2026-10-03T17:00:00+08:00",
  sessionId: "session-no-status",
});
assert(noStatusStart.ok, "status-less task could not start");
const noStatusStarted: TaskSnapshot = Object.freeze({
  ...noStatus,
  status: "IN-PROCESS",
  description: String(noStatusStart.taskPatch.description),
});
const noStatusStop = planTaskAction({
  intent: "stop",
  task: noStatusStarted,
  currentWorkId: noStatusId,
  now: "2026-10-03T17:10:00+08:00",
});
assert(noStatusStop.ok, "status-less task could not stop");
assert(noStatusStop.taskPatch.status === null, "unset STATUS was not restored");
assert(
  !("percentComplete" in noStatusStop.taskPatch),
  "status-less Stop must preserve current percent instead of rewriting it",
);

const fullyProgressed: TaskSnapshot = Object.freeze({
  ...base,
  uid: "uid-100-percent",
  status: null,
  completed: true,
  percentComplete: 100,
});
const completedByPercent = planTaskAction({
  intent: "start",
  task: fullyProgressed,
  currentWorkId: null,
  now: "2026-10-03T17:11:00+08:00",
  sessionId: "must-not-open",
});
assert(
  !completedByPercent.ok && completedByPercent.reason === "finished",
  "Thunderbird-completed Task was startable",
);

const progressChanged: TaskSnapshot = Object.freeze({
  ...started,
  percentComplete: 67,
});
const stopAfterProgressEdit = planTaskAction({
  intent: "stop",
  task: progressChanged,
  currentWorkId: id,
  now: "2026-10-03T17:12:00+08:00",
});
assert(stopAfterProgressEdit.ok, "Stop after progress edit was rejected");
assert(
  !("percentComplete" in stopAfterProgressEdit.taskPatch),
  "Stop would overwrite progress changed during the session",
);

const statusChanged: TaskSnapshot = Object.freeze({
  ...started,
  status: "NEEDS-ACTION",
});
const stopAfterStatusEdit = planTaskAction({
  intent: "stop",
  task: statusChanged,
  currentWorkId: id,
  now: "2026-10-03T17:13:00+08:00",
});
assert(stopAfterStatusEdit.ok, "Stop after external STATUS edit was rejected");
assert(
  !("status" in stopAfterStatusEdit.taskPatch),
  "Stop would overwrite a STATUS changed during the session",
);

const malformed: TaskSnapshot = Object.freeze({
  ...base,
  description: "hello\n[CALDAV-ASSISTANT-WORKLOG v1]\n{broken",
});
const malformedPlan = planTaskAction({
  intent: "start",
  task: malformed,
  currentWorkId: null,
  now: "2026-10-03T16:00:00+08:00",
  sessionId: "session-x",
});
assert(
  !malformedPlan.ok && malformedPlan.reason === "description-invalid",
  "malformed worklog allowed destructive write",
);

const userText = "line 1\n\nline 2 中文 😀\n";
const noBlock = parseWorkDescription(userText);
assert(noBlock.ok, "plain description failed");
assert(serializeWorkDescription(noBlock.value) === userText, "plain description changed");

const withSuffix =
  "before user text\n\n" +
  "[CALDAV-ASSISTANT-WORKLOG v1]\n" +
  JSON.stringify([{
    id: "suffix-session",
    start: "2026-10-03T12:00:00+08:00",
    end: "2026-10-03T12:10:00+08:00",
    result: "stop",
    before: {status: null},
  }]) +
  "\n[/CALDAV-ASSISTANT-WORKLOG]" +
  "\nafter user text 😀";
const suffixParsed = parseWorkDescription(withSuffix);
assert(suffixParsed.ok, "description with user suffix failed to parse");
assert(suffixParsed.value.prefix === "before user text\n\n", "prefix changed");
assert(suffixParsed.value.suffix === "\nafter user text 😀", "suffix changed");
assert(
  serializeWorkDescription(suffixParsed.value) === withSuffix,
  "user text around worklog did not round-trip exactly",
);

const alreadyClosed = stoppedParsed.ok ? stoppedParsed.value : null;
assert(alreadyClosed, "closed parse unavailable");
const sameClose = closeSession(
  alreadyClosed,
  "session-1",
  "2026-10-03T16:30:00+08:00",
  "stop",
);
assert(sameClose !== null, "idempotent close rejected");
assert(
  serializeWorkDescription(sameClose) === String(stop.taskPatch.description),
  "idempotent close changed description",
);

const migrated = migrateLegacySettings({
  taskView: "incomplete",
  taskCalendarId: "tasks",
  workCalendarId: "obsolete-work-events",
  wordpress: {
    transport: "application-password",
    username: "andrew",
    applicationPassword: "secret-value-must-survive",
    wordpressPath: "/var/www/html/wordpress",
  },
  anotherFutureSetting: 123,
});
assert(migrated.schemaVersion === 1, "settings schema missing");
assert(!("workCalendarId" in migrated), "obsolete Work Event setting migrated");
assert(migrated.anotherFutureSetting === 123, "unknown user setting lost");
const migratedWp = migrated.wordpress as Record<string, unknown>;
assert(
  migratedWp.applicationPassword === "secret-value-must-survive",
  "existing password was not migrated",
);

const redacted = redactSettingsForDiagnostics(migrated);
const redactedWp = redacted.wordpress as Record<string, unknown>;
assert(
  redactedWp.applicationPassword === "[configured]",
  "diagnostics leaked password",
);

console.log("clean-room core: PASS");
