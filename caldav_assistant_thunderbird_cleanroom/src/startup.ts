import {
  CleanroomBrowserApi,
  createStoragePort,
  createThunderbirdTaskPort,
} from "./browser-ports.js";
import {
  LegacyActiveMigrationResult,
  migrateLegacyActiveSession,
} from "./legacy-active-migration.js";
import {
  SettingsLoadResult,
  StorageCurrentWork,
  loadOrMigrateSettings,
} from "./storage-runtime.js";
import {
  ReconcileResult,
  reconcileCurrentWork,
} from "./workflow-service.js";

export interface StartupReport {
  readonly settings: SettingsLoadResult;
  readonly legacyActive: LegacyActiveMigrationResult;
  readonly currentWork: ReconcileResult | null;
}

export async function startCleanroom(
  browserApi: CleanroomBrowserApi
): Promise<StartupReport> {
  const storage = createStoragePort(browserApi.storage.local);
  const tasks = createThunderbirdTaskPort(browserApi.ThunderbirdTasks);
  const currentWork = new StorageCurrentWork(storage);

  const settings = await loadOrMigrateSettings(storage);
  const legacyActive = await migrateLegacyActiveSession(
    storage,
    tasks,
    currentWork
  );

  // Unresolved legacy migration is intentionally a hard recovery state. Do
  // not run reconciliation afterward, because "idle" would hide the fact that
  // a legacy active Task still needs attention.
  if (legacyActive.kind === "unresolved") {
    return Object.freeze({
      settings,
      legacyActive,
      currentWork: null,
    });
  }

  const current = await reconcileCurrentWork({
    tasks,
    currentWork,
  });

  return Object.freeze({
    settings,
    legacyActive,
    currentWork: current,
  });
}
