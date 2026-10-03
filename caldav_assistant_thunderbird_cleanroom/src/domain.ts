export type TaskStatus =
  | ""
  | "NEEDS-ACTION"
  | "IN-PROCESS"
  | "COMPLETED"
  | "CANCELLED";

export type WorkResult = "stop" | "complete" | "cancel";

export interface TaskRef {
  readonly calendarId: string;
  readonly uid: string;
  readonly recurrenceId: string;
}

export interface TaskSnapshot extends TaskRef {
  readonly title: string;
  readonly status: TaskStatus;
  readonly percentComplete: number;
  readonly description: string;
}

export interface WorkSession {
  readonly id: string;
  readonly start: string;
  readonly end: string | null;
  readonly result: WorkResult | null;
  readonly before: {
    readonly status: TaskStatus;
    readonly percentComplete: number;
  };
}

export interface WorkLogV1 {
  readonly version: 1;
  readonly sessions: readonly WorkSession[];
}

export interface ParsedDescription {
  readonly ok: true;
  readonly userText: string;
  readonly workLog: WorkLogV1;
}

export interface CorruptDescription {
  readonly ok: false;
  readonly reason: string;
  readonly original: string;
}

export type DescriptionParseResult = ParsedDescription | CorruptDescription;

export interface TaskPatch {
  readonly description: string;
  readonly status?: TaskStatus;
  readonly percentComplete?: number;
}

export type WorkIntent = "start" | "stop" | "complete" | "cancel";

export interface AcceptedPlan {
  readonly ok: true;
  readonly intent: WorkIntent;
  readonly taskPatch: TaskPatch;
  readonly nextCurrentWorkId: string | null;
  readonly closedSession: WorkSession | null;
}

export interface RejectedPlan {
  readonly ok: false;
  readonly intent: WorkIntent;
  readonly reason:
    | "finished"
    | "current-work-exists"
    | "not-current"
    | "description-corrupt"
    | "open-session-exists"
    | "open-session-missing";
}

export type WorkPlan = AcceptedPlan | RejectedPlan;
