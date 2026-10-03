import {TaskStatus} from "./domain";

export type ThunderbirdTaskFilter =
  | "all"
  | "notstarted"
  | "overdue"
  | "open"
  | "completed"
  | "throughcurrent"
  | "throughtoday"
  | "throughsevendays";

export interface TaskQueryOptions {
  readonly filter: ThunderbirdTaskFilter;
  readonly search: string;
  readonly calendarIds: readonly string[];
}

export interface TaskListItem {
  readonly taskId: string;
  readonly calendarId: string;
  readonly calendarName: string;
  readonly title: string;
  readonly status: TaskStatus;
  readonly percentComplete: number;
  readonly due: string | null;
  readonly categories: readonly string[];
}

export interface TaskQueryFailure {
  readonly calendarId: string;
  readonly message: string;
}

export interface TaskQueryResult {
  readonly items: readonly TaskListItem[];
  readonly complete: boolean;
  readonly failures: readonly TaskQueryFailure[];
}

export interface TaskQuery {
  query(options: TaskQueryOptions): Promise<TaskQueryResult>;
}
