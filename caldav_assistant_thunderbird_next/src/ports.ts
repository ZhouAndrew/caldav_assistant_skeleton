import {AppSettings} from "./migration/legacy-settings";
import {TaskPatch, TaskSnapshot} from "./domain";

export interface TaskWriteExpectation {
  readonly description: string;
  readonly status: TaskSnapshot["status"];
  readonly percentComplete: number;
}

export interface TaskRepository {
  get(taskId: string): Promise<TaskSnapshot | null>;
  update(
    taskId: string,
    patch: TaskPatch,
    expected: TaskWriteExpectation
  ): Promise<void>;
}

export interface TaskScanFailure {
  readonly calendarId: string;
  readonly message: string;
}

export interface TaskScanResult {
  readonly tasks: readonly TaskSnapshot[];
  readonly complete: boolean;
  readonly failures: readonly TaskScanFailure[];
}

export interface TaskCatalog {
  scanStored(): Promise<TaskScanResult>;
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
