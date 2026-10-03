import {
  AssistantRuntime,
  RecurrenceId,
  TaskRef,
  TaskUid,
  CalendarId,
  WorkTaskId,
  makeWorkTaskId,
  parseWorkTaskId,
} from "./domain";

export interface LegacyTaskRef {
  readonly calendarId?: unknown;
  readonly id?: unknown;
  readonly recurrenceId?: unknown;
}

export interface LegacyRuntime {
  readonly currentTask?: LegacyTaskRef | null;
  readonly state?: unknown;
  readonly currentWorkEvent?: unknown;
  readonly segmentStartedAtMs?: unknown;
  readonly accumulatedMs?: unknown;
  readonly taskBeforeStart?: unknown;
}

function nonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  return value.length ? value : null;
}

export function legacyTaskRef(value: LegacyTaskRef | null | undefined): TaskRef | null {
  const calendarId = nonEmptyString(value?.calendarId);
  const id = nonEmptyString(value?.id);
  if (!calendarId || !id) return null;

  return Object.freeze({
    calendarId: calendarId as CalendarId,
    id: id as TaskUid,
    recurrenceId:
      (typeof value?.recurrenceId === "string" ? value.recurrenceId : "") as RecurrenceId,
  });
}

export function currentWorkIdFromLegacyRuntime(
  legacy: LegacyRuntime | null | undefined,
): WorkTaskId | null {
  const ref = legacyTaskRef(legacy?.currentTask);
  return ref ? makeWorkTaskId(ref) : null;
}

/**
 * Compatibility reader for Phase 1.
 *
 * The new currentWorkId wins only when it is structurally valid. Otherwise the
 * old 0.3.15 runtime.currentTask is used to reconstruct the new single dynamic
 * state variable. No legacy workflow fields become authoritative in the new core.
 */
export function normalizeRuntime(
  persistedCurrentWorkId: unknown,
  legacy: LegacyRuntime | null | undefined,
): AssistantRuntime {
  if (
    typeof persistedCurrentWorkId === "string" &&
    parseWorkTaskId(persistedCurrentWorkId as WorkTaskId)
  ) {
    return Object.freeze({
      currentWorkId: persistedCurrentWorkId as WorkTaskId,
    });
  }

  return Object.freeze({
    currentWorkId: currentWorkIdFromLegacyRuntime(legacy),
  });
}
