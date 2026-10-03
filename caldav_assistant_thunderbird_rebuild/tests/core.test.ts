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
assert(stop.taskPatch.percentComplete === 35, "stop did not restore percent");
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
