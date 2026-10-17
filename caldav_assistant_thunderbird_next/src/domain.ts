export type TaskStatus =
  | "NEEDS-ACTION"
  | "IN-PROCESS"
  | "COMPLETED"
  | "CANCELLED";

export type WorkResult = "stop" | "complete" | "cancel";

export interface TaskIdentity {
  readonly calendarId: string;
  readonly uid: string;
  readonly recurrenceId: string;
}

export interface TaskSnapshot extends TaskIdentity {
  readonly taskId: string;
  readonly title: string;
  readonly description: string;
  readonly status: TaskStatus;
  readonly percentComplete: number;
}

export interface WorkSessionBefore {
  readonly status: TaskStatus;
  readonly percentComplete: number;
}

export interface WorkSession {
  readonly id: string;
  readonly start: string;
  readonly end: string | null;
  readonly result: WorkResult | null;
  readonly before: WorkSessionBefore;
}

export interface WorkLog {
  readonly version: 1;
  readonly sessions: readonly WorkSession[];
}

export interface ParsedDescription {
  readonly userText: string;
  readonly workLog: WorkLog;
}

export type WorkIntent = "start" | "stop" | "complete" | "cancel";

export interface TaskPatch {
  readonly description: string;
  readonly status: TaskStatus;
  readonly percentComplete: number;
}

export interface AcceptedTransition {
  readonly ok: true;
  readonly intent: WorkIntent;
  readonly taskPatch: TaskPatch;
  readonly nextCurrentWorkId: string | null;
  readonly closedSession: WorkSession | null;
}

export type RejectionReason =
  | "finished"
  | "current-work-exists"
  | "not-current"
  | "description-invalid"
  | "open-session-exists"
  | "open-session-missing";

export interface RejectedTransition {
  readonly ok: false;
  readonly intent: WorkIntent;
  readonly reason: RejectionReason;
}

export type PlannedTransition = AcceptedTransition | RejectedTransition;
