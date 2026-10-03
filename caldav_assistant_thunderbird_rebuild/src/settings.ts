export const LEGACY_SETTINGS_KEY = "caldavAssistant.settings";
export const SETTINGS_KEY = "caldavAssistant.v2.settings";

export interface SettingsV1 {
  readonly schemaVersion: 1;
  readonly taskView?: unknown;
  readonly taskCalendarId?: unknown;
  readonly wordpress?: Readonly<Record<string, unknown>>;
  readonly [key: string]: unknown;
}

/**
 * Pure one-time settings migration.
 *
 * The legacy object is user configuration, not workflow code.  We preserve every
 * configuration field except the obsolete Work-Event calendar selector.
 * Secret values (including wordpress.applicationPassword) are copied as opaque
 * values and are never returned separately, logged, normalized or printed.
 */
export function migrateLegacySettings(
  legacy: Readonly<Record<string, unknown>> | null | undefined,
): SettingsV1 {
  const source = legacy && typeof legacy === "object" ? legacy : {};
  const next: Record<string, unknown> = {...source};
  delete next.workCalendarId;
  next.schemaVersion = 1;

  if (source.wordpress && typeof source.wordpress === "object") {
    next.wordpress = Object.freeze({
      ...(source.wordpress as Record<string, unknown>),
    });
  }

  return Object.freeze(next) as SettingsV1;
}

export function redactSettingsForDiagnostics(
  settings: Readonly<Record<string, unknown>>,
): Readonly<Record<string, unknown>> {
  const copy: Record<string, unknown> = {...settings};
  const wordpress = copy.wordpress;
  if (wordpress && typeof wordpress === "object") {
    const wp = {...(wordpress as Record<string, unknown>)};
    if ("applicationPassword" in wp) {
      wp.applicationPassword = wp.applicationPassword ? "[configured]" : "";
    }
    if ("password" in wp) wp.password = wp.password ? "[configured]" : "";
    copy.wordpress = Object.freeze(wp);
  }
  return Object.freeze(copy);
}
