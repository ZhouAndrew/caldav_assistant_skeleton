export type Brand<T, Tag extends string> = T & {
  readonly __brand: Tag;
};

export type CalendarId = Brand<string, "CalendarId">;
export type TaskUid = Brand<string, "TaskUid">;
export type RecurrenceId = Brand<string, "RecurrenceId">;
export type WorkTaskId = Brand<string, "WorkTaskId">;

export type TaskStatus =
  | "NEEDS-ACTION"
  | "IN-PROCESS"
  | "COMPLETED"
  | "CANCELLED";

export type WorkAction =
  | "start"
  | "pause"
  | "resume"
  | "complete"
  | "cancel"
  | "switch-away";

export interface TaskRef {
  readonly calendarId: CalendarId;
  readonly id: TaskUid;
  readonly recurrenceId: RecurrenceId;
}

export interface TaskSnapshot extends TaskRef {
  readonly workTaskId: WorkTaskId;
  readonly title: string;
  readonly status: TaskStatus;
  readonly paused: boolean;
  readonly percentComplete: number;
}

export interface AssistantRuntime {
  /**
   * The only authoritative dynamic work-session state owned by the Assistant.
   *
   * Task status, pause state, progress, dates and categories remain Thunderbird /
   * CalDAV facts and must be derived by reading the referenced VTODO.
   */
  readonly currentWorkId: WorkTaskId | null;
}

export type DerivedWorkState = "idle" | "working" | "paused";

function encodePart(value: string): string {
  return encodeURIComponent(value);
}

function decodePart(value: string): string {
  return decodeURIComponent(value);
}

/**
 * Build one opaque Assistant work id from Thunderbird's real task identity.
 *
 * Thunderbird task identity is composite: Calendar id + VTODO UID + recurrence id.
 * Persisting the opaque WorkTaskId lets Assistant runtime keep exactly one dynamic
 * state variable while still addressing recurring tasks safely.
 */
export function makeWorkTaskId(ref: TaskRef): WorkTaskId {
  return [
    encodePart(ref.calendarId),
    encodePart(ref.id),
    encodePart(ref.recurrenceId),
  ].join("|") as WorkTaskId;
}

export function parseWorkTaskId(value: WorkTaskId): TaskRef | null {
  const parts = String(value).split("|");
  if (parts.length !== 3) return null;

  try {
    return Object.freeze({
      calendarId: decodePart(parts[0] ?? "") as CalendarId,
      id: decodePart(parts[1] ?? "") as TaskUid,
      recurrenceId: decodePart(parts[2] ?? "") as RecurrenceId,
    });
  } catch {
    return null;
  }
}

export function taskRef(
  calendarId: string,
  id: string,
  recurrenceId = "",
): TaskRef {
  return Object.freeze({
    calendarId: calendarId as CalendarId,
    id: id as TaskUid,
    recurrenceId: recurrenceId as RecurrenceId,
  });
}
