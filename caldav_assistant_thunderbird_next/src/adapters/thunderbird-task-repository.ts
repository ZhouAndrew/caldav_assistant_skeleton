import {TaskPatch, TaskSnapshot, TaskStatus} from "../domain";
import {TaskCatalog, TaskRepository, TaskScanResult, TaskWriteExpectation} from "../ports";
import {TaskCalendarInfo, TaskListItem, TaskQuery, TaskQueryOptions, TaskQueryResult} from "../task-query";
import {decodeTaskId, encodeTaskId} from "../task-id";

export interface NativeTaskView {
  readonly calendarId: string;
  readonly uid: string;
  readonly recurrenceId: string;
  readonly title: string;
  readonly description: string;
  readonly status: TaskStatus;
  readonly percentComplete: number;
}

export interface NativeTaskScanResult {
  readonly tasks: readonly NativeTaskView[];
  readonly complete: boolean;
  readonly failures: readonly {
    readonly calendarId: string;
    readonly message: string;
  }[];
}

export interface NativeTaskCalendar {
  readonly id: string;
  readonly name: string;
  readonly disabled: boolean;
  readonly inComposite: boolean;
  readonly readOnly: boolean;
}

export interface NativeTaskListItem {
  readonly calendarId: string;
  readonly calendarName: string;
  readonly uid: string;
  readonly recurrenceId: string;
  readonly title: string;
  readonly status: TaskStatus;
  readonly percentComplete: number;
  readonly due: string | null;
  readonly categories: readonly string[];
}

export interface NativeTaskQueryResult {
  readonly tasks: readonly NativeTaskListItem[];
  readonly complete: boolean;
  readonly failures: readonly {
    readonly calendarId: string;
    readonly message: string;
  }[];
}

export interface NativeTasksApi {
  getTask(
    calendarId: string,
    uid: string,
    recurrenceId: string
  ): Promise<NativeTaskView | null>;

  updateTask(
    calendarId: string,
    uid: string,
    recurrenceId: string,
    patch: TaskPatch,
    expected: TaskWriteExpectation
  ): Promise<NativeTaskView>;

  scanStoredTasks(): Promise<NativeTaskScanResult>;

  queryTasks(options: TaskQueryOptions): Promise<NativeTaskQueryResult>;

  listTaskCalendars(): Promise<readonly NativeTaskCalendar[]>;
}

function snapshot(native: NativeTaskView): TaskSnapshot {
  const identity = {
    calendarId: native.calendarId,
    uid: native.uid,
    recurrenceId: native.recurrenceId,
  };
  return Object.freeze({
    ...identity,
    taskId: encodeTaskId(identity),
    title: native.title,
    description: native.description,
    status: native.status,
    percentComplete: native.percentComplete,
  });
}

function listItem(native: NativeTaskListItem): TaskListItem {
  const identity = {
    calendarId: native.calendarId,
    uid: native.uid,
    recurrenceId: native.recurrenceId,
  };
  return Object.freeze({
    taskId: encodeTaskId(identity),
    calendarId: native.calendarId,
    calendarName: native.calendarName,
    title: native.title,
    status: native.status,
    percentComplete: native.percentComplete,
    due: native.due,
    categories: Object.freeze([...native.categories]),
  });
}

export class ThunderbirdTaskRepository
  implements TaskRepository, TaskCatalog, TaskQuery {
  constructor(private readonly api: NativeTasksApi) {}

  async get(taskId: string): Promise<TaskSnapshot | null> {
    const ref = decodeTaskId(taskId);
    if (!ref) throw new Error("Malformed taskId.");
    const item = await this.api.getTask(
      ref.calendarId,
      ref.uid,
      ref.recurrenceId
    );
    return item ? snapshot(item) : null;
  }

  async update(
    taskId: string,
    patch: TaskPatch,
    expected: TaskWriteExpectation
  ): Promise<void> {
    const ref = decodeTaskId(taskId);
    if (!ref) throw new Error("Malformed taskId.");
    await this.api.updateTask(
      ref.calendarId,
      ref.uid,
      ref.recurrenceId,
      patch,
      expected
    );
  }

  async scanStored(): Promise<TaskScanResult> {
    const result = await this.api.scanStoredTasks();
    return Object.freeze({
      tasks: Object.freeze(result.tasks.map(snapshot)),
      complete: result.complete,
      failures: Object.freeze(result.failures.map(item => Object.freeze({...item}))),
    });
  }

  async listCalendars(): Promise<readonly TaskCalendarInfo[]> {
    const calendars = await this.api.listTaskCalendars();
    return Object.freeze(
      calendars.map(calendar => Object.freeze({...calendar}))
    );
  }

  async query(options: TaskQueryOptions): Promise<TaskQueryResult> {
    const result = await this.api.queryTasks(options);
    return Object.freeze({
      items: Object.freeze(result.tasks.map(listItem)),
      complete: result.complete,
      failures: Object.freeze(
        result.failures.map(item => Object.freeze({...item}))
      ),
    });
  }
}
