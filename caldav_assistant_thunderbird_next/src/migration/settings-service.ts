import {RawSettingsStore} from "../ports";
import {AppSettings, migrateLegacySettings} from "./legacy-settings";

export interface SettingsMigrationResult {
  readonly migrated: boolean;
  readonly settings: AppSettings;
}

/**
 * One-time settings migration.
 *
 * Deliberately accepts no DiagnosticSink: settings may contain credentials and
 * the safest logging policy is to never pass the migration payload to logging.
 */
export async function ensureV2Settings(
  store: RawSettingsStore
): Promise<SettingsMigrationResult> {
  const existing = await store.getV2Settings();
  if (existing?.schemaVersion === 2) {
    return Object.freeze({migrated: false, settings: existing});
  }

  const legacy = await store.getLegacySettings();
  const mapped = migrateLegacySettings(legacy, null);
  await store.setV2Settings(mapped.settings);
  return Object.freeze({
    migrated: mapped.migrated,
    settings: mapped.settings,
  });
}
