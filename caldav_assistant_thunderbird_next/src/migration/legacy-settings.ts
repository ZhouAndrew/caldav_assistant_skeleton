export interface WordPressSettings {
  readonly transport: "auto" | "application-password" | "wp-cli";
  readonly baseUrl: string;
  readonly username: string;
  readonly applicationPassword: string;
  readonly wordpressPath: string;
  readonly wpCliCommand: string;
  readonly allowUntrustedTls: boolean;
  readonly dailyWorkLogEnabled: boolean;
}

export interface AppSettings {
  readonly schemaVersion: 2;
  readonly wordpress: WordPressSettings;
}

export interface MigrationResult {
  readonly migrated: boolean;
  readonly settings: AppSettings;
}

const DEFAULT_WORDPRESS: WordPressSettings = Object.freeze({
  transport: "auto",
  baseUrl: "",
  username: "",
  applicationPassword: "",
  wordpressPath: "/var/www/html/wordpress",
  wpCliCommand: "wp",
  allowUntrustedTls: false,
  dailyWorkLogEnabled: false,
});

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function bool(value: unknown): boolean {
  return value === true;
}

function transport(value: unknown): WordPressSettings["transport"] {
  return value === "application-password" || value === "wp-cli"
    ? value
    : "auto";
}

/**
 * One-time pure mapping from persisted 0.3.x settings to the new schema.
 *
 * This function deliberately returns the password only as part of settings data.
 * Callers must never include its input or output in diagnostic/log payloads.
 */
export function migrateLegacySettings(
  legacySettings: unknown,
  existingV2: AppSettings | null
): MigrationResult {
  if (existingV2?.schemaVersion === 2) {
    return Object.freeze({migrated: false, settings: existingV2});
  }

  const root =
    legacySettings && typeof legacySettings === "object"
      ? legacySettings as Record<string, unknown>
      : {};
  const oldWp =
    root.wordpress && typeof root.wordpress === "object"
      ? root.wordpress as Record<string, unknown>
      : {};

  const hasLegacy = Object.keys(oldWp).length > 0;
  const migrated: WordPressSettings = Object.freeze({
    transport: transport(oldWp.transport),
    baseUrl: text(oldWp.baseUrl),
    username: text(oldWp.username),
    applicationPassword: text(oldWp.applicationPassword),
    wordpressPath: text(oldWp.wordpressPath) || DEFAULT_WORDPRESS.wordpressPath,
    wpCliCommand:
      text(oldWp.wpCliCommand) ||
      text(oldWp.wpCliExecutable) ||
      DEFAULT_WORDPRESS.wpCliCommand,
    allowUntrustedTls: bool(oldWp.allowUntrustedTls),
    dailyWorkLogEnabled:
      typeof oldWp.dailyWorkLogEnabled === "boolean"
        ? oldWp.dailyWorkLogEnabled
        : hasLegacy,
  });

  return Object.freeze({
    migrated: hasLegacy,
    settings: Object.freeze({
      schemaVersion: 2,
      wordpress: migrated,
    }),
  });
}
