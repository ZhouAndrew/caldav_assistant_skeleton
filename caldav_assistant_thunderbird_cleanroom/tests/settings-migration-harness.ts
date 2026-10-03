import {migrateLegacySettings} from "../src/settings-migration";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const secret = "abcd EFGH 1234";
const migrated = migrateLegacySettings({
  taskView: "all",
  taskCalendarId: "calendar-1",
  workCalendarId: "obsolete-work-calendar",
  wordpress: {
    dailyWorkLogEnabled: true,
    transport: "application-password",
    baseUrl: "https://andrew.local/",
    username: "andrew",
    applicationPassword: secret,
    allowUntrustedTls: true,
    wordpressPath: "/var/www/html/wordpress",
    wpCliCommand: "wp --quiet",
  },
});

assert(migrated.settings.taskView === "all", "task view was not migrated");
assert(
  migrated.settings.taskCalendarId === "calendar-1",
  "task calendar was not migrated"
);
assert(
  migrated.settings.wordpress.applicationPassword === secret,
  "Application Password must migrate exactly"
);
assert(
  !("workCalendarId" in migrated.settings),
  "obsolete Work Calendar setting leaked into new settings"
);
assert(
  migrated.diagnostic.wordpressPasswordConfigured === true,
  "diagnostic should report configured password"
);
assert(
  !JSON.stringify(migrated.diagnostic).includes(secret),
  "diagnostic leaked the Application Password"
);

const defaults = migrateLegacySettings(null);
assert(defaults.settings.taskView === "incomplete", "default task view is wrong");
assert(defaults.settings.wordpress.transport === "auto", "default transport is wrong");
assert(
  defaults.settings.wordpress.wordpressPath === "/var/www/html/wordpress",
  "default WordPress path is wrong"
);
assert(defaults.settings.wordpress.wpCliCommand === "wp", "default WP-CLI is wrong");

console.log("settings-migration-harness: PASS");
