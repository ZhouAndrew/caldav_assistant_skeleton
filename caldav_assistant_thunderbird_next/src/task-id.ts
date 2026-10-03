import {TaskIdentity} from "./domain";

function enc(value: string): string {
  return encodeURIComponent(value);
}

function dec(value: string): string {
  return decodeURIComponent(value);
}

export function encodeTaskId(task: TaskIdentity): string {
  return [enc(task.calendarId), enc(task.uid), enc(task.recurrenceId)].join("|");
}

export function decodeTaskId(taskId: string): TaskIdentity | null {
  const parts = taskId.split("|");
  if (parts.length !== 3) return null;

  try {
    return Object.freeze({
      calendarId: dec(parts[0] ?? ""),
      uid: dec(parts[1] ?? ""),
      recurrenceId: dec(parts[2] ?? ""),
    });
  } catch {
    return null;
  }
}
