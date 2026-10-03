export type TaskStatus =
  | "NEEDS-ACTION"
  | "IN-PROCESS"
  | "COMPLETED"
  | "CANCELLED";

export type StoredTaskStatus = TaskStatus | null;

export type WorkResult = "stop" | "complete" | "cancel";

export interface TaskRef {
  readonly calendarId: string;
  readonly uid: string;
  readonly recurrenceId: string;
}

export interface TaskSnapshot extends TaskRef {
  readonly title: string;
  readonly status: StoredTaskStatus;
  readonly percentComplete: number;
  readonly description: string;
}

export interface WorkSession {
  readonly id: string;
  readonly start: string;
  readonly end: string | null;
  readonly result: WorkResult | null;
  readonly before: {
    readonly status: StoredTaskStatus;
    readonly percentComplete: number;
  };
}

export interface ParsedWorkDescription {
  readonly prefix: string;
  readonly suffix: string;
  readonly sessions: readonly WorkSession[];
}

export type WorkIntent = "start" | "stop" | "complete" | "cancel";

export interface TaskPatch {
  readonly status?: StoredTaskStatus;
  readonly percentComplete?: number;
  readonly description?: string;
}

export interface AcceptedPlan {
  readonly ok: true;
  readonly intent: WorkIntent;
  readonly taskPatch: Readonly<TaskPatch>;
  readonly nextCurrentWorkId: string | null;
  readonly closedSession: WorkSession | null;
}

export type PlanRejection =
  | "finished"
  | "current-work-exists"
  | "not-current"
  | "description-invalid"
  | "open-session-exists"
  | "open-session-missing"
  | "open-session-ambiguous";

export interface RejectedPlan {
  readonly ok: false;
  readonly intent: WorkIntent;
  readonly reason: PlanRejection;
}

export type TaskActionPlan = AcceptedPlan | RejectedPlan;

export function taskId(ref: TaskRef): string {
  return JSON.stringify([
    String(ref.calendarId),
    String(ref.uid),
    String(ref.recurrenceId || ""),
  ]);
}

export function parseTaskId(value: string): TaskRef | null {
  try {
    const parsed: unknown = JSON.parse(value);
    if (
      !Array.isArray(parsed) ||
      parsed.length !== 3 ||
      parsed.some(part => typeof part !== "string") ||
      !parsed[0] ||
      !parsed[1]
    ) {
      return null;
    }
    return Object.freeze({
      calendarId: parsed[0],
      uid: parsed[1],
      recurrenceId: parsed[2],
    });
  } catch {
    return null;
  }
}

export function isFinished(task: Pick<TaskSnapshot, "status">): boolean {
  return task.status === "COMPLETED" || task.status === "CANCELLED";
}

export function normalizePercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.trunc(value)));
}
