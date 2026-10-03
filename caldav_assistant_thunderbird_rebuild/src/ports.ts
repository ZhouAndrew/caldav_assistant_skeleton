import {TaskPatch, TaskRef, TaskSnapshot} from "./domain";

export interface CalendarSummary {
  readonly id: string;
  readonly name: string;
  readonly disabled: boolean;
  readonly readOnly: boolean;
  readonly writable: boolean;
  readonly supportsTasks: boolean;
}

export interface TaskRecord extends TaskSnapshot {
  readonly calendarName: string;
  readonly writable: boolean;
  readonly priority: number;
  readonly categories: readonly string[];
  readonly start: unknown;
  readonly due: unknown;
  readonly completedDate: unknown;
  readonly recurring: boolean;
}

export interface TaskQuery {
  readonly calendarId?: string;
  readonly includeOccurrences?: boolean;
  readonly rangeStart?: string;
  readonly rangeEnd?: string;
}

export interface TaskPort {
  listCalendars(): Promise<readonly CalendarSummary[]>;
  listTasks(query?: TaskQuery): Promise<readonly TaskRecord[]>;
  getTask(ref: TaskRef): Promise<TaskRecord>;
  updateTask(ref: TaskRef, patch: Readonly<TaskPatch>): Promise<TaskRecord>;
}
