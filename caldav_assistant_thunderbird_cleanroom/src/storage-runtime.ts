import {CleanSettings, SettingsMigration, migrateLegacySettings} from "./settings-migration";
import {CurrentWorkPort} from "./workflow-service";

export const SETTINGS_KEY = "caldavAssistant.v2.settings";
export const CURRENT_WORK_KEY = "caldavAssistant.v2.currentWorkId";
export const LEGACY_SETTINGS_KEY = "caldavAssistant.settings";

export interface StorageAreaPort {
  get(keys: string | readonly string[]): Promise<Record<string, unknown>>;
  set(values: Record<string, unknown>): Promise<void>;
  remove(keys: string | readonly string[]): Promise<void>;
}

function isWordPressSettings(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const object = value as Record<string, unknown>;
  return (
    typeof object.dailyWorkLogEnabled === "boolean" &&
    (object.transport === "auto" ||
      object.transport === "application-password" ||
      object.transport === "wp-cli") &&
    typeof object.baseUrl === "string" &&
    typeof object.username === "string" &&
    typeof object.applicationPassword === "string" &&
    typeof object.allowUntrustedTls === "boolean" &&
    typeof object.wordpressPath === "string" &&
    typeof object.wpCliCommand === "string"
  );
}

export function isCleanSettings(value: unknown): value is CleanSettings {
  if (!value || typeof value !== "object") return false;
  const object = value as Record<string, unknown>;
  return (
    object.schemaVersion === 1 &&
    typeof object.taskView === "string" &&
    typeof object.taskCalendarId === "string" &&
    isWordPressSettings(object.wordpress)
  );
}

export interface SettingsLoadResult {
  readonly settings: CleanSettings;
  readonly migrated: boolean;
  readonly diagnostic: SettingsMigration["diagnostic"] | null;
}

/**
 * Load the new settings key. On first clean-room startup only, migrate the old
 * settings object into the new namespaced key.
 *
 * Legacy keys are intentionally not deleted here. Active-session migration is
 * a later, separate transaction and may still need old data.
 */
export async function loadOrMigrateSettings(
  storage: StorageAreaPort
): Promise<SettingsLoadResult> {
  const existing = await storage.get(SETTINGS_KEY);
  const current = existing[SETTINGS_KEY];
  if (isCleanSettings(current)) {
    return Object.freeze({
      settings: current,
      migrated: false,
      diagnostic: null,
    });
  }

  const legacyValues = await storage.get(LEGACY_SETTINGS_KEY);
  const migration = migrateLegacySettings(legacyValues[LEGACY_SETTINGS_KEY]);
  await storage.set({[SETTINGS_KEY]: migration.settings});

  const readBack = await storage.get(SETTINGS_KEY);
  const stored = readBack[SETTINGS_KEY];
  if (!isCleanSettings(stored)) {
    throw new Error("Migrated settings read-back failed.");
  }

  return Object.freeze({
    settings: stored,
    migrated: true,
    diagnostic: migration.diagnostic,
  });
}

export async function saveSettings(
  storage: StorageAreaPort,
  settings: CleanSettings
): Promise<CleanSettings> {
  if (!isCleanSettings(settings)) {
    throw new Error("Refusing to save invalid settings.");
  }
  await storage.set({[SETTINGS_KEY]: settings});
  const readBack = (await storage.get(SETTINGS_KEY))[SETTINGS_KEY];
  if (!isCleanSettings(readBack)) {
    throw new Error("Settings read-back failed.");
  }
  return readBack;
}

export class StorageCurrentWork implements CurrentWorkPort {
  constructor(private readonly storage: StorageAreaPort) {}

  async getCurrentWorkId(): Promise<string | null> {
    const value = (await this.storage.get(CURRENT_WORK_KEY))[CURRENT_WORK_KEY];
    return typeof value === "string" && value ? value : null;
  }

  async setCurrentWorkId(value: string | null): Promise<void> {
    if (value === null) {
      await this.storage.remove(CURRENT_WORK_KEY);
      return;
    }
    if (!value) throw new Error("currentWorkId cannot be empty.");
    await this.storage.set({[CURRENT_WORK_KEY]: value});
  }
}
