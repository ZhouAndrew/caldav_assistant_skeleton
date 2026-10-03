"use strict";

const assert = require("node:assert/strict");

const data = {
  "caldavAssistant.settings": {
    taskView: "open",
    taskCalendarId: "tasks",
    workCalendarId: "obsolete-work-calendar",
    wordpress: {
      transport: "application-password",
      username: "user",
      applicationPassword: "existing-secret",
      wordpressPath: "/var/www/html/wordpress",
    },
    futureSetting: {keep: true},
  },
};

global.browser = {
  storage: {
    local: {
      async get(keys) {
        const requested = Array.isArray(keys) ? keys : [keys];
        return Object.fromEntries(
          requested
            .filter(key => Object.prototype.hasOwnProperty.call(data, key))
            .map(key => [key, data[key]])
        );
      },
      async set(values) {
        Object.assign(data, values);
      },
      async remove(key) {
        delete data[key];
      },
    },
  },
};

require("../addon/storage.js");

(async () => {
  const settings = await global.RebuildStorage.ensureSettings();
  assert.equal(settings.schemaVersion, 1);
  assert.equal("workCalendarId" in settings, false);
  assert.deepEqual(settings.futureSetting, {keep: true});
  assert.equal(
    settings.wordpress.applicationPassword,
    "existing-secret",
    "existing WordPress password must survive the in-place migration"
  );
  assert.equal(
    data["caldavAssistant.settings"].wordpress.applicationPassword,
    "existing-secret"
  );
  assert.equal(data["caldavAssistant.settingsMigrationV2"], 1);

  assert.equal(await global.RebuildStorage.getCurrentWorkId(), null);
  await global.RebuildStorage.setCurrentWorkId("[\"cal\",\"uid\",\"\"]");
  assert.equal(
    await global.RebuildStorage.getCurrentWorkId(),
    "[\"cal\",\"uid\",\"\"]"
  );
  await global.RebuildStorage.setCurrentWorkId(null);
  assert.equal(await global.RebuildStorage.getCurrentWorkId(), null);

  console.log("storage-migration: PASS");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
