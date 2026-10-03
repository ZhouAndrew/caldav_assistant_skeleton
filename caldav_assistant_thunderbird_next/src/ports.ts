import {AppSettings} from "./migration/legacy-settings";
import {TaskPatch, TaskSnapshot} from "./domain";

export interface TaskRepository {
  get(taskId: string): Promise<TaskSnapshot | null>;
  update(taskId: string, patch: TaskPatch): Promise<void>;
}

export interface CurrentWorkStore {
  get(): Promise<string | null>;
  set(value: string | null): Promise<void>;
}

export interface RawSettingsStore {
  getLegacySettings(): Promise<unknown>;
  getV2Settings(): Promise<AppSettings | null>;
  setV2Settings(settings: AppSettings): Promise<void>;
}

export interface DiagnosticSink {
  record(entry: {
    readonly kind: string;
    readonly success: boolean;
    readonly taskId?: string;
    readonly message?: string;
  }): Promise<void>;
}
