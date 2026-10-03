import {AppSettings, isAppSettings} from "../migration/legacy-settings";
import {CurrentWorkStore, RawSettingsStore} from "../ports";
import {decodeTaskId} from "../task-id";

export const STORAGE_KEYS = Object.freeze({
  legacySettings: "caldavAssistant.settings",
  settingsV2: "caldavAssistant.settings.v2",
  currentWorkId: "caldavAssistant.currentWorkId",
});

export interface StorageArea {
  get(keys: string | readonly string[]): Promise<Record<string, unknown>>;
  set(values: Record<string, unknown>): Promise<void>;
  remove(keys: string | readonly string[]): Promise<void>;
}

export class BrowserStorageAdapter
  implements CurrentWorkStore, RawSettingsStore {
  constructor(private readonly storage: StorageArea) {}

  async get(): Promise<string | null> {
    const values = await this.storage.get(STORAGE_KEYS.currentWorkId);
    const value = values[STORAGE_KEYS.currentWorkId];
    if (value === undefined || value === null) return null;
    if (typeof value !== "string" || !decodeTaskId(value)) {
      throw new Error("Stored currentWorkId is malformed.");
    }
    return value;
  }

  async set(value: string | null): Promise<void> {
    if (value !== null && !decodeTaskId(value)) {
      throw new Error("Refusing to store malformed currentWorkId.");
    }
    await this.storage.set({[STORAGE_KEYS.currentWorkId]: value});
  }

  async getLegacySettings(): Promise<unknown> {
    const values = await this.storage.get(STORAGE_KEYS.legacySettings);
    return values[STORAGE_KEYS.legacySettings] ?? null;
  }

  async getV2Settings(): Promise<AppSettings | null> {
    const values = await this.storage.get(STORAGE_KEYS.settingsV2);
    const value = values[STORAGE_KEYS.settingsV2];
    return isAppSettings(value) ? value : null;
  }

  async setV2Settings(settings: AppSettings): Promise<void> {
    if (!isAppSettings(settings)) {
      throw new Error("Refusing to store malformed v2 settings.");
    }
    await this.storage.set({[STORAGE_KEYS.settingsV2]: settings});
  }
}
