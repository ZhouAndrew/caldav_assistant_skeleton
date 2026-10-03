"use strict";

globalThis.RebuildTaskPort = Object.freeze({
  listCalendars: () => browser.TaskBridge.listCalendars(),
  listTasks: options => browser.TaskBridge.listTasks(options || {}),
  getTask: ref => browser.TaskBridge.getTask(ref),
  updateTask: (ref, changes, expected) =>
    browser.TaskBridge.updateTask(ref, changes, expected),
});
