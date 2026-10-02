#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const refresh = require(path.join(__dirname, "refresh_core.js"));

function messengerWith(bridge) {
  return {assistantCalendar: bridge};
}

async function testCombinedSuccess() {
  const messenger = messengerWith({
    async refreshSnapshot() {
      return {
        ok: true,
        tasks: [
          {id: "a", status: "NEEDS-ACTION", completed: false},
          {id: "done", status: "COMPLETED", completed: true},
        ],
        work: {currentTaskId: "a", workedTaskIds: ["a"]},
        diagnostics: {steps: [{stage: "calendar-manager", success: true}]},
      };
    },
  });
  const result = await refresh.resilientRefresh({
    messenger,
    fallback: async () => {
      throw new Error("fallback should not run");
    },
    timeoutMs: 50,
  });
  assert.equal(result.source, "local");
  assert.deepEqual(result.data.tasks.map(task => task.id), ["a"]);
  assert.equal(result.data.work.currentTaskId, "a");
}

async function testGenericExperimentFailureFallsBack() {
  const messenger = messengerWith({
    async refreshSnapshot() {
      throw new Error("An unexpected error occurred");
    },
  });
  const result = await refresh.resilientRefresh({
    messenger,
    fallback: async () => ({
      tasks: [{id: "b"}],
      state: {current_task_id: null, paused_task_ids: []},
    }),
    timeoutMs: 50,
  });
  assert.equal(result.source, "fallback");
  assert.match(result.localError, /unexpected error/i);
  assert.equal(result.data.tasks[0].id, "b");
}

async function testStructuredExperimentFailureFallsBack() {
  const messenger = messengerWith({
    async refreshSnapshot() {
      return {
        ok: false,
        error: "calendar-manager: getCalendars failed",
        diagnostics: {
          steps: [{stage: "calendar-manager", success: false}],
        },
      };
    },
  });
  const result = await refresh.resilientRefresh({
    messenger,
    fallback: async () => ({tasks: [], state: {}}),
    timeoutMs: 50,
  });
  assert.equal(result.source, "fallback");
  assert.match(result.localError, /calendar-manager/);
  assert.equal(result.localDiagnostics.steps[0].success, false);
}

async function testTimeoutFallsBack() {
  const messenger = messengerWith({
    refreshSnapshot() {
      return new Promise(() => {});
    },
  });
  const result = await refresh.resilientRefresh({
    messenger,
    fallback: async () => ({tasks: [], state: {}}),
    timeoutMs: 5,
  });
  assert.equal(result.source, "fallback");
  assert.match(result.localError, /timed out/i);
}

async function testLegacyBridgeStillWorks() {
  const messenger = messengerWith({
    async listTasks() {
      return [{id: "legacy", status: "NEEDS-ACTION"}];
    },
    async workState() {
      return {currentTaskId: "legacy", workedTaskIds: ["legacy"]};
    },
  });
  const result = await refresh.resilientRefresh({
    messenger,
    fallback: async () => {
      throw new Error("fallback should not run");
    },
    timeoutMs: 50,
  });
  assert.equal(result.source, "local");
  assert.equal(result.data.source, "thunderbird-calendar-cache-legacy");
  assert.equal(result.data.tasks[0].id, "legacy");
}

async function testDoubleFailurePreservesBothErrors() {
  const messenger = messengerWith({
    async refreshSnapshot() {
      throw new Error("local bridge exploded");
    },
  });
  await assert.rejects(
    refresh.resilientRefresh({
      messenger,
      fallback: async () => {
        throw new Error("native fallback exploded");
      },
      timeoutMs: 50,
    }),
    error => {
      assert.match(error.message, /local bridge exploded/);
      assert.match(error.message, /native fallback exploded/);
      assert.match(error.localError, /local bridge exploded/);
      assert.match(error.fallbackError, /native fallback exploded/);
      return true;
    }
  );
}

async function main() {
  for (let round = 0; round < 50; round += 1) {
    await testCombinedSuccess();
    await testGenericExperimentFailureFallsBack();
    await testStructuredExperimentFailureFallsBack();
    await testTimeoutFallsBack();
    await testLegacyBridgeStillWorks();
    await testDoubleFailurePreservesBothErrors();
  }
  console.log("Thunderbird refresh simulation: 300 scenarios PASS");
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
