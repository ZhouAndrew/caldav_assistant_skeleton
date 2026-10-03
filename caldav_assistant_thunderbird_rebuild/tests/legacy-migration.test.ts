import {taskId} from "../src/domain";
import {
  classifyPersistedPointer,
  findLegacyStartFact,
  parseLegacyTaskId,
} from "../src/legacy-migration";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const ref = {
  calendarId: "calendar|with delimiter",
  uid: "uid / 中文",
  recurrenceId: "20261003T090000Z",
};
const legacyId = [
  encodeURIComponent(ref.calendarId),
  encodeURIComponent(ref.uid),
  encodeURIComponent(ref.recurrenceId),
].join("|");

const parsed = parseLegacyTaskId(legacyId);
assert(parsed?.calendarId === ref.calendarId, "legacy calendar id failed");
assert(parsed?.uid === ref.uid, "legacy uid failed");
assert(parsed?.recurrenceId === ref.recurrenceId, "legacy recurrence failed");

const classified = classifyPersistedPointer(legacyId, null);
assert(classified.kind === "legacy", "legacy pointer was not classified");
assert(
  classified.kind === "legacy" && classified.id === taskId(ref),
  "legacy pointer did not convert to new opaque id",
);

const modern = taskId(ref);
const modernClassified = classifyPersistedPointer(modern, null);
assert(modernClassified.kind === "new", "new pointer was mistaken for legacy");

const runtimeOnly = classifyPersistedPointer(undefined, {
  currentTask: {
    calendarId: ref.calendarId,
    id: ref.uid,
    recurrenceId: ref.recurrenceId,
  },
});
assert(runtimeOnly.kind === "legacy", "0.3.15 runtime ref was not recovered");

const lastReceipt = {
  action: "start",
  success: true,
  startedAt: "2026-10-03T08:00:00+08:00",
  task: {
    calendarId: ref.calendarId,
    id: ref.uid,
    recurrenceId: ref.recurrenceId,
    beforeStatus: "",
  },
};
const direct = findLegacyStartFact({
  ref,
  lastReceipt,
  auditRecords: [{
    scope: "workflow",
    action: "start",
    success: true,
    timestamp: "2026-10-03T01:00:00Z",
    details: {
      action: "start",
      success: true,
      task: {
        calendarId: ref.calendarId,
        id: ref.uid,
        recurrenceId: ref.recurrenceId,
        beforeStatus: "NEEDS-ACTION",
      },
    },
  }],
});
assert(direct?.source === "last-receipt", "lastReceipt did not win");
assert(direct?.beforeStatus === null, "empty legacy STATUS was not preserved as null");
assert(direct?.start === "2026-10-03T00:00:00.000Z", "lastReceipt start time wrong");

const audit = findLegacyStartFact({
  ref,
  lastReceipt: {action: "stop", success: true},
  auditRecords: [
    {
      scope: "workflow",
      action: "start",
      success: true,
      timestamp: "2026-10-03T00:00:00Z",
      details: {
        action: "start",
        success: true,
        startedAt: "2026-10-03T08:30:00+08:00",
        task: {
          calendarId: ref.calendarId,
          id: ref.uid,
          recurrenceId: ref.recurrenceId,
          beforeStatus: "NEEDS-ACTION",
        },
      },
    },
  ],
});
assert(audit?.source === "audit", "audit Start was not recovered");
assert(audit?.beforeStatus === "NEEDS-ACTION", "audit before STATUS wrong");
assert(audit?.start === "2026-10-03T00:30:00.000Z", "audit start wrong");

const runtime = findLegacyStartFact({
  ref,
  runtime: {
    currentTask: {
      calendarId: ref.calendarId,
      id: ref.uid,
      recurrenceId: ref.recurrenceId,
    },
    segmentStartedAtMs: Date.parse("2026-10-03T09:00:00+08:00"),
    taskBeforeStart: {status: "IN-PROCESS"},
    currentWorkEvent: {id: "ignored-on-purpose"},
  },
});
assert(runtime?.source === "legacy-runtime", "runtime fallback failed");
assert(runtime?.beforeStatus === "IN-PROCESS", "runtime before STATUS wrong");
assert(runtime?.start === "2026-10-03T01:00:00.000Z", "runtime timestamp wrong");

const missing = findLegacyStartFact({
  ref,
  runtime: {
    currentTask: {calendarId: ref.calendarId, id: ref.uid},
    currentWorkEvent: {id: "must-not-be-used"},
  },
});
assert(missing === null, "migration invented a Start time from Work Event data");

console.log("legacy-migration: PASS");
