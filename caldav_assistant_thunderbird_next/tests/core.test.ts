import {TaskSnapshot} from "../src/domain";
import {decodeTaskId, encodeTaskId} from "../src/task-id";
import {
  parseWorkDescription,
  serializeWorkDescription,
} from "../src/work-description";
import {planTaskAction} from "../src/workflow";
import {migrateLegacySettings} from "../src/migration/legacy-settings";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const identity = {
  calendarId: "calendar/任务",
  uid: "uid|42",
  recurrenceId: "20261003T090000",
};
const taskId = encodeTaskId(identity);
const roundTripId = decodeTaskId(taskId);
assert(roundTripId?.calendarId === identity.calendarId, "calendarId round-trip failed");
assert(roundTripId?.uid === identity.uid, "uid round-trip failed");
assert(roundTripId?.recurrenceId === identity.recurrenceId, "recurrenceId round-trip failed");

const originalText = "第一行\n第二行 🙂\n\n用户自己的 [CALDAV] 文本";
const task: TaskSnapshot = Object.freeze({
  ...identity,
  taskId,
  title: "Clean-room task",
  description: originalText,
  status: "NEEDS-ACTION",
  percentComplete: 35,
});

const start = planTaskAction(
  "start",
  task,
  null,
  "2026-10-03T19:00:00+08:00",
  "session-1"
);
assert(start.ok, "Start was rejected");
assert(start.taskPatch.status === "IN-PROCESS", "Start status wrong");
assert(start.taskPatch.percentComplete === 35, "Start changed progress");
assert(start.nextCurrentWorkId === taskId, "Start pointer wrong");

const parsedStarted = parseWorkDescription(start.taskPatch.description);
assert(parsedStarted.ok, "Started description did not parse");
assert(parsedStarted.value.userText === originalText, "User description changed");
assert(parsedStarted.value.workLog.sessions.length === 1, "Session was not appended");
assert(parsedStarted.value.workLog.sessions[0]?.end === null, "Session is not open");

const startedTask: TaskSnapshot = Object.freeze({
  ...task,
  description: start.taskPatch.description,
  status: "IN-PROCESS",
});

const duplicateStart = planTaskAction(
  "start",
  startedTask,
  taskId,
  "2026-10-03T19:05:00+08:00",
  "session-2"
);
assert(!duplicateStart.ok && duplicateStart.reason === "current-work-exists",
  "Duplicate Start should be rejected");

const stop = planTaskAction(
  "stop",
  startedTask,
  taskId,
  "2026-10-03T19:30:00+08:00",
  "unused"
);
assert(stop.ok, "Stop was rejected");
assert(stop.taskPatch.status === "NEEDS-ACTION", "Stop did not restore status");
assert(stop.taskPatch.percentComplete === 35, "Stop did not restore progress");
assert(stop.nextCurrentWorkId === null, "Stop did not clear pointer");
assert(stop.closedSession?.result === "stop", "Stop result not recorded");
assert(stop.closedSession?.end === "2026-10-03T19:30:00+08:00", "Stop end missing");

const parsedStopped = parseWorkDescription(stop.taskPatch.description);
assert(parsedStopped.ok, "Stopped description did not parse");
assert(parsedStopped.value.userText === originalText, "Stop changed user description");
assert(
  serializeWorkDescription(parsedStopped.value) === stop.taskPatch.description,
  "Description serialization is not idempotent"
);

const completeStart = planTaskAction(
  "start",
  task,
  null,
  "2026-10-03T20:00:00+08:00",
  "session-complete"
);
assert(completeStart.ok, "Complete scenario Start failed");
const completeTask: TaskSnapshot = Object.freeze({
  ...task,
  description: completeStart.taskPatch.description,
  status: "IN-PROCESS",
});
const complete = planTaskAction(
  "complete",
  completeTask,
  taskId,
  "2026-10-03T20:15:00+08:00",
  "unused"
);
assert(complete.ok, "Complete failed");
assert(complete.taskPatch.status === "COMPLETED", "Complete status wrong");
assert(complete.taskPatch.percentComplete === 100, "Complete percent wrong");
assert(complete.closedSession?.result === "complete", "Complete result missing");

const cancelStart = planTaskAction(
  "start",
  task,
  null,
  "2026-10-03T21:00:00+08:00",
  "session-cancel"
);
assert(cancelStart.ok, "Cancel scenario Start failed");
const cancelTask: TaskSnapshot = Object.freeze({
  ...task,
  description: cancelStart.taskPatch.description,
  status: "IN-PROCESS",
});
const cancel = planTaskAction(
  "cancel",
  cancelTask,
  taskId,
  "2026-10-03T21:10:00+08:00",
  "unused"
);
assert(cancel.ok, "Cancel failed");
assert(cancel.taskPatch.status === "CANCELLED", "Cancel status wrong");
assert(cancel.closedSession?.result === "cancel", "Cancel result missing");

const otherTask: TaskSnapshot = Object.freeze({
  ...task,
  taskId: encodeTaskId({calendarId: "calendar/任务", uid: "other", recurrenceId: ""}),
});
const blocked = planTaskAction(
  "start",
  otherTask,
  taskId,
  "2026-10-03T22:00:00+08:00",
  "session-other"
);
assert(!blocked.ok && blocked.reason === "current-work-exists",
  "Another active task did not block Start");

const malformedTask: TaskSnapshot = Object.freeze({
  ...task,
  description:
    originalText +
    "\n\n[CALDAV-ASSISTANT-WORKLOG v1]\n{bad json}\n[/CALDAV-ASSISTANT-WORKLOG]",
});
const malformed = planTaskAction(
  "start",
  malformedTask,
  null,
  "2026-10-03T22:30:00+08:00",
  "session-malformed"
);
assert(!malformed.ok && malformed.reason === "description-invalid",
  "Malformed work log should block destructive write");

const migrated = migrateLegacySettings({
  wordpress: {
    transport: "application-password",
    baseUrl: "https://wordpress.example.invalid",
    username: "legacy-user",
    applicationPassword: "TEST-SECRET-DO-NOT-LOG",
    wordpressPath: "/srv/wordpress",
    wpCliCommand: "wp",
    allowUntrustedTls: true,
    dailyWorkLogEnabled: true,
  },
}, null);
assert(migrated.migrated, "Legacy settings were not detected");
assert(
  migrated.settings.wordpress.applicationPassword === "TEST-SECRET-DO-NOT-LOG",
  "Application Password was not migrated exactly"
);
assert(migrated.settings.wordpress.username === "legacy-user",
  "WordPress username was not migrated");
assert(migrated.settings.wordpress.wordpressPath === "/srv/wordpress",
  "WordPress path was not migrated");

console.log("clean-room core: PASS");
