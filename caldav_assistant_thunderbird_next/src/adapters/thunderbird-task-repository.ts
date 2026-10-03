import {TaskPatch, TaskSnapshot, TaskStatus} from "../domain";
import {TaskRepository} from "../ports";
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
    patch: TaskPatch
  ): Promise<NativeTaskView>;
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

export class ThunderbirdTaskRepository implements TaskRepository {
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

  async update(taskId: string, patch: TaskPatch): Promise<void> {
    const ref = decodeTaskId(taskId);
    if (!ref) throw new Error("Malformed taskId.");
    await this.api.updateTask(
      ref.calendarId,
      ref.uid,
      ref.recurrenceId,
      patch
    );
  }
}
