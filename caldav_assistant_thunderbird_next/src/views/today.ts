import {TaskSnapshot, WorkSession} from "../domain";
import {parseWorkDescription} from "../work-description";

export interface TodayWorkRow {
  readonly taskId: string;
  readonly title: string;
  readonly sessionId: string;
  readonly start: string;
  readonly end: string | null;
  readonly result: WorkSession["result"];
}

export interface TodayView {
  readonly date: string;
  readonly rows: readonly TodayWorkRow[];
  readonly warnings: readonly string[];
}

function localDateKey(iso: string): string | null {
  // Work-session timestamps are stored with their local UTC offset. Use the
  // calendar date embedded in that timestamp instead of the machine running
  // the view, so CI/server timezone cannot move a session to another day.
  const match = /^(\d{4}-\d{2}-\d{2})T/.exec(iso);
  return match?.[1] ?? null;
}

export function deriveTodayView(
  tasks: readonly TaskSnapshot[],
  localDate: string
): TodayView {
  const rows: TodayWorkRow[] = [];
  const warnings: string[] = [];

  for (const task of tasks) {
    const parsed = parseWorkDescription(task.description);
    if (!parsed.ok) {
      warnings.push(`Malformed work log: ${task.taskId}`);
      continue;
    }
    for (const session of parsed.value.workLog.sessions) {
      if (localDateKey(session.start) !== localDate) continue;
      rows.push(Object.freeze({
        taskId: task.taskId,
        title: task.title,
        sessionId: session.id,
        start: session.start,
        end: session.end,
        result: session.result,
      }));
    }
  }

  rows.sort((a, b) => a.start.localeCompare(b.start));
  return Object.freeze({
    date: localDate,
    rows: Object.freeze(rows),
    warnings: Object.freeze(warnings),
  });
}
