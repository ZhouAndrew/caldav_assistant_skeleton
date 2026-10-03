import {
  TaskPatch,
  TaskRef,
  TaskSnapshot,
  TaskStatus,
} from "./domain.js";
import {StorageAreaPort} from "./storage-runtime.js";
import {ThunderbirdTaskPort} from "./workflow-service.js";

interface ThunderbirdTasksApi {
  getTask(
    calendarId: string,
    uid: string,
    recurrenceId?: string
  ): Promise<unknown>;
  updateTask(
    calendarId: string,
    uid: string,
    recurrenceId: string,
    patch: TaskPatch
  ): Promise<unknown>;
}

interface StorageLocalApi {
  get(keys: string | readonly string[]): Promise<Record<string, unknown>>;
  set(values: Record<string, unknown>): Promise<void>;
  remove(keys: string | readonly string[]): Promise<void>;
}

export interface CleanroomBrowserApi {
  readonly ThunderbirdTasks: ThunderbirdTasksApi;
  readonly storage: {
    readonly local: StorageLocalApi;
  };
}

function object(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? value as Record<string, unknown>
    : null;
}

function taskStatus(value: unknown): TaskStatus | null {
  if (typeof value !== "string") return null;
  const text = value.toUpperCase();
  return text === "" ||
    text === "NEEDS-ACTION" ||
    text === "IN-PROCESS" ||
    text === "COMPLETED" ||
    text === "CANCELLED"
    ? text
    : null;
}

function taskSnapshot(value: unknown): TaskSnapshot {
  const item = object(value);
  if (!item) throw new Error("ThunderbirdTasks returned a non-object Task.");

  const calendarId =
    typeof item.calendarId === "string" ? item.calendarId : "";
  const uid = typeof item.uid === "string" ? item.uid : "";
  const recurrenceId =
    typeof item.recurrenceId === "string" ? item.recurrenceId : "";
  const title = typeof item.title === "string" ? item.title : "";
  const status = taskStatus(item.status);
  const percentComplete = Number(item.percentComplete);
  const description =
    typeof item.description === "string" ? item.description : "";

  if (!calendarId || !uid) {
    throw new Error("ThunderbirdTasks returned a Task without identity.");
  }
  if (status === null) {
    throw new Error("ThunderbirdTasks returned an unsupported VTODO STATUS.");
  }
  if (
    !Number.isInteger(percentComplete) ||
    percentComplete < 0 ||
    percentComplete > 100
  ) {
    throw new Error(
      "ThunderbirdTasks returned invalid PERCENT-COMPLETE."
    );
  }

  return Object.freeze({
    calendarId,
    uid,
    recurrenceId,
    title,
    status,
    percentComplete,
    description,
  });
}

export function createThunderbirdTaskPort(
  api: ThunderbirdTasksApi
): ThunderbirdTaskPort {
  return Object.freeze({
    async getTask(ref: TaskRef): Promise<TaskSnapshot> {
      return taskSnapshot(
        await api.getTask(ref.calendarId, ref.uid, ref.recurrenceId)
      );
    },

    async updateTask(
      ref: TaskRef,
      patch: TaskPatch
    ): Promise<TaskSnapshot> {
      return taskSnapshot(
        await api.updateTask(
          ref.calendarId,
          ref.uid,
          ref.recurrenceId,
          patch
        )
      );
    },
  });
}

export function createStoragePort(
  storage: StorageLocalApi
): StorageAreaPort {
  return Object.freeze({
    get: keys => storage.get(keys),
    set: values => storage.set(values),
    remove: keys => storage.remove(keys),
  });
}
