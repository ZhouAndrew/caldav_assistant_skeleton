import {TaskRef} from "./domain";

export function makeTaskId(ref: TaskRef): string {
  return [
    encodeURIComponent(ref.calendarId),
    encodeURIComponent(ref.uid),
    encodeURIComponent(ref.recurrenceId),
  ].join("|");
}

export function parseTaskId(value: string): TaskRef | null {
  const parts = String(value || "").split("|");
  if (parts.length !== 3) return null;

  try {
    const calendarId = decodeURIComponent(parts[0] ?? "");
    const uid = decodeURIComponent(parts[1] ?? "");
    const recurrenceId = decodeURIComponent(parts[2] ?? "");
    if (!calendarId || !uid) return null;
    return Object.freeze({calendarId, uid, recurrenceId});
  } catch {
    return null;
  }
}
