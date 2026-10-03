export interface WordPressSettings {
  readonly dailyWorkLogEnabled: boolean;
  readonly transport: "auto" | "application-password" | "wp-cli";
  readonly baseUrl: string;
  readonly username: string;
  readonly applicationPassword: string;
  readonly allowUntrustedTls: boolean;
  readonly wordpressPath: string;
  readonly wpCliCommand: string;
}

export interface CleanSettings {
  readonly taskView: string;
  readonly taskCalendarId: string;
  readonly wordpress: WordPressSettings;
}

export interface SettingsMigration {
  readonly settings: CleanSettings;
  readonly diagnostic: {
    readonly migrated: true;
    readonly taskCalendarConfigured: boolean;
    readonly wordpressTransport: WordPressSettings["transport"];
    readonly wordpressPasswordConfigured: boolean;
  };
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function transport(value: unknown): WordPressSettings["transport"] {
  return value === "application-password" || value === "wp-cli" || value === "auto"
    ? value
    : "auto";
}

/**
 * One-time pure migration from 0.3.16 browser.storage.local settings.
 *
 * This is deliberately data-only. It does not import or call any legacy module.
 * The Application Password is copied exactly as persisted and is never included
 * in the diagnostic projection.
 */
export function migrateLegacySettings(value: unknown): SettingsMigration {
  const legacy =
    value && typeof value === "object"
      ? value as Record<string, unknown>
      : {};
  const wp =
    legacy.wordpress && typeof legacy.wordpress === "object"
      ? legacy.wordpress as Record<string, unknown>
      : {};

  const wordpress: WordPressSettings = Object.freeze({
    dailyWorkLogEnabled: bool(wp.dailyWorkLogEnabled, true),
    transport: transport(wp.transport),
    baseUrl: text(wp.baseUrl).trim(),
    username: text(wp.username).trim(),
    applicationPassword: text(wp.applicationPassword),
    allowUntrustedTls: bool(wp.allowUntrustedTls, false),
    wordpressPath: text(wp.wordpressPath).trim() || "/var/www/html/wordpress",
    wpCliCommand:
      text(wp.wpCliCommand).trim() ||
      text(wp.wpCliExecutable).trim() ||
      "wp",
  });

  const settings: CleanSettings = Object.freeze({
    taskView: text(legacy.taskView).trim() || "incomplete",
    taskCalendarId: text(legacy.taskCalendarId),
    wordpress,
  });

  return Object.freeze({
    settings,
    diagnostic: Object.freeze({
      migrated: true,
      taskCalendarConfigured: Boolean(settings.taskCalendarId),
      wordpressTransport: wordpress.transport,
      wordpressPasswordConfigured: Boolean(wordpress.applicationPassword),
    }),
  });
}
