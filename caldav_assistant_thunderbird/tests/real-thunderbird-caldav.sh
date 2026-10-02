#!/usr/bin/env bash
set -euo pipefail

TB_VERSION="${1:-153.0.2esr}"
TB_TIMEZONE="${2:-UTC}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
TB_PID=""
XVFB_PID=""
RADICALE_PID=""
REPORT_PID=""

cleanup() {
  set +e
  [[ -n "$TB_PID" ]] && kill "$TB_PID" 2>/dev/null || true
  [[ -n "$XVFB_PID" ]] && kill "$XVFB_PID" 2>/dev/null || true
  [[ -n "$REPORT_PID" ]] && kill "$REPORT_PID" 2>/dev/null || true
  [[ -n "$RADICALE_PID" ]] && kill "$RADICALE_PID" 2>/dev/null || true

  if [[ -n "${ACCEPTANCE_ARTIFACT_DIR:-}" ]]; then
    mkdir -p "$ACCEPTANCE_ARTIFACT_DIR"
    for candidate in       "$TMP/report.json"       "$TMP/thunderbird.stdout"       "$TMP/thunderbird.stderr"       "$TMP/thunderbird-restart.stdout"       "$TMP/thunderbird-restart.stderr"       "$TMP/radicale.log"       "$TMP/xvfb.log"; do
      [[ -f "$candidate" ]] && cp "$candidate" "$ACCEPTANCE_ARTIFACT_DIR/" || true
    done
    if [[ -n "${PROFILE:-}" ]]; then
      for candidate in "$PROFILE"/caldav-assistant-experimental-*.log "$PROFILE"/caldav-assistant-experimental-*.log.1; do
        [[ -f "$candidate" ]] && cp "$candidate" "$ACCEPTANCE_ARTIFACT_DIR/" || true
      done
    fi
  fi

  rm -rf "$TMP"
}
trap cleanup EXIT

echo "== Build production XPI =="
chmod +x "$ROOT/packaging/build-xpi.sh"
"$ROOT/packaging/build-xpi.sh" "$TMP/base.xpi"
python3 "$ROOT/tests/check-xpi.py" "$TMP/base.xpi"

echo "== Build test-instrumented XPI =="
mkdir -p "$TMP/addon"
(
  cd "$TMP/addon"
  unzip -q "$TMP/base.xpi"
)
python3 - "$TMP/addon" <<'PY'
from pathlib import Path
import json
import sys

root = Path(sys.argv[1])
manifest_path = root / "manifest.json"
manifest = json.loads(manifest_path.read_text())
permissions = manifest.setdefault("permissions", [])
host = "http://127.0.0.1/*"
if host not in permissions:
    permissions.append(host)

manifest["experiment_apis"]["AcceptanceTaskFix"] = {
    "schema": "api/AcceptanceTaskFix/schema.json",
    "parent": {
        "scopes": ["addon_parent"],
        "paths": [["AcceptanceTaskFix"]],
        "script": "api/AcceptanceTaskFix/implementation.js",
    },
}
taskfix_dir = root / "api" / "AcceptanceTaskFix"
taskfix_dir.mkdir(parents=True, exist_ok=True)
(taskfix_dir / "schema.json").write_text(r'''[
  {
    "namespace": "AcceptanceTaskFix",
    "functions": [
      {
        "name": "openTasksAndCheck",
        "type": "function",
        "async": true,
        "parameters": [],
        "returns": {"type": "any"}
      },
      {
        "name": "selectTaskByTitle",
        "type": "function",
        "async": true,
        "parameters": [
          {"name": "title", "type": "string"}
        ],
        "returns": {"type": "any"}
      }
    ]
  }
]
''')
(taskfix_dir / "implementation.js").write_text(r'''"use strict";

var { ExtensionCommon } = ChromeUtils.importESModule(
  "resource://gre/modules/ExtensionCommon.sys.mjs"
);

function delay(window, ms) {
  return new Promise(resolve => window.setTimeout(resolve, ms));
}

this.AcceptanceTaskFix = class extends ExtensionCommon.ExtensionAPI {
  getAPI() {
    return {
      AcceptanceTaskFix: {
        async openTasksAndCheck() {
          const wm = Cc["@mozilla.org/appshell/window-mediator;1"]
            .getService(Ci.nsIWindowMediator);
          const window = wm.getMostRecentWindow("mail:3pane");
          if (!window) {
            return {ok: false, error: "No Thunderbird 3-pane window"};
          }

          if (typeof window.calSwitchToTaskMode === "function") {
            window.calSwitchToTaskMode();
          } else {
            window.document.getElementById("tasksButton")?.click();
          }

          for (let attempt = 0; attempt < 80; attempt++) {
            const taskTree = window.document.getElementById("calendar-task-tree");
            const toolbar = window.document.getElementById("task-actions-toolbar");
            const status = window.document.getElementById("task-actions-status");
            const contextStatus = window.document.getElementById("task-context-menu-status");
            if (taskTree && toolbar && status && contextStatus) {
              return {
                ok: true,
                marker: String(window.__taskfixAddonState?.marker || ""),
                taskTree: true,
                toolbar: true,
                statusButton: true,
                contextStatus: true,
              };
            }
            await delay(window, 100);
          }

          return {
            ok: false,
            error: "TaskFix controls did not appear in the real Tasks UI",
            marker: String(window.__taskfixAddonState?.marker || ""),
            taskTree: Boolean(window.document.getElementById("calendar-task-tree")),
            toolbar: Boolean(window.document.getElementById("task-actions-toolbar")),
            statusButton: Boolean(window.document.getElementById("task-actions-status")),
            contextStatus: Boolean(window.document.getElementById("task-context-menu-status")),
          };
        },
        async selectTaskByTitle(title) {
          const wm = Cc["@mozilla.org/appshell/window-mediator;1"]
            .getService(Ci.nsIWindowMediator);
          const window = wm.getMostRecentWindow("mail:3pane");
          if (!window) return {ok: false, error: "No Thunderbird 3-pane window"};

          if (typeof window.calSwitchToTaskMode === "function") {
            window.calSwitchToTaskMode();
          } else {
            window.document.getElementById("tasksButton")?.click();
          }

          for (let attempt = 0; attempt < 120; attempt++) {
            const taskTree = window.document.getElementById("calendar-task-tree");
            const rows = taskTree?.mTaskArray || [];
            for (let row = 0; row < rows.length; row++) {
              const task = taskTree.getTaskAtRow(row);
              if (String(task?.title || "") !== String(title || "")) continue;
              taskTree.mTreeView?.selection?.select(row);
              taskTree.currentIndex = row;
              taskTree.focus?.();
              await delay(window, 50);
              return {
                ok: true,
                id: String(task?.id || ""),
                calendarId: String(task?.calendar?.superCalendar?.id || task?.calendar?.id || ""),
                recurrenceId: String(task?.recurrenceId?.icalString || ""),
                title: String(task?.title || ""),
              };
            }
            await delay(window, 100);
          }
          return {ok: false, error: "Task row not found: " + title};
        },
      },
    };
  }
};
''')

manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

task_picker_acceptance = r'''
async function __pickerWaitFor(predicate, label, timeoutMs = 20000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error("Task picker timeout: " + label);
}

function __pickerAssert(condition, message) {
  if (!condition) throw new Error(message);
}

function __pickerButton(label) {
  return [...$("actions").querySelectorAll("button")].find(
    button => button.textContent === label
  );
}

async function __pickerWaitForNewReceipt(action, previousId, timeoutMs = 15000) {
  let receipt = null;
  await __pickerWaitFor(async () => {
    receipt = await AssistantStorage.getLastReceipt();
    return receipt?.id !== previousId && receipt?.action === action;
  }, "new receipt " + action, timeoutMs);
  __pickerAssert(receipt?.success, action + " failed: " + (receipt?.error || receipt?.summary || ""));
  return receipt;
}

async function __runTaskPickerAcceptance() {
  const mode = new URLSearchParams(location.search).get("acceptance");
  if (!mode) return;

  let targetId = "seed-task";
  let targetTitle = "Seed task from Radicale";
  if (mode === "switch") {
    const saved = await browser.storage.local.get("caldavAssistant.acceptanceSwitchTarget");
    const target = saved["caldavAssistant.acceptanceSwitchTarget"];
    __pickerAssert(target?.id, "Switch target reference was not persisted by acceptance setup");
    targetId = target.id;
    targetTitle = target.title || "Switch target task";
  }

  await __pickerWaitFor(
    () =>
      state.tasks.some(task => task.id === targetId) &&
      [...$("task-list").children].some(
        row => row.querySelector?.(".item-title")?.textContent === targetTitle
      ),
    "target Task render"
  );

  const nativeFilters = [
    "throughcurrent",
    "throughtoday",
    "throughsevendays",
    "notstarted",
    "overdue",
    "completed",
    "open",
    "all",
  ];
  for (const value of nativeFilters) {
    __pickerAssert(
      Boolean(document.querySelector('input[name="task-view"][value="' + value + '"]')),
      "Task picker lost Thunderbird native Task filter " + value
    );
  }
  __pickerAssert(
    document.querySelector('input[name="task-view"][value="open"]')?.checked,
    "Task picker did not map its default to Thunderbird native open filter"
  );
  __pickerAssert(Boolean(document.getElementById("task-calendar-list")), "Task picker lost native Calendar selector");
  __pickerAssert(
    [...$("task-calendar-list").querySelectorAll(".native-calendar-row")].some(
      row => row.textContent.includes("Acceptance")
    ),
    "Task picker did not inherit the visible Thunderbird Calendar list"
  );
  __pickerAssert(Boolean(document.getElementById("task-search")), "Task picker lost search");
  __pickerAssert(!document.getElementById("receipt"), "Detailed result log leaked into Task picker");
  __pickerAssert(!document.getElementById("cancel-confirm"), "Cancel workflow leaked into Task picker");

  // Human-path check that the search is delegated through Thunderbird's
  // native calFilter rather than the old custom title-only filter.
  $("task-search").value = targetTitle;
  $("task-search").dispatchEvent(new Event("input", {bubbles: true}));
  await __pickerWaitFor(
    () =>
      state.tasks.some(task => task.id === targetId) &&
      [...$("task-list").children].some(
        row => row.querySelector?.(".item-title")?.textContent === targetTitle
      ),
    "native Task search"
  );

  const targetRow = [...$("task-list").children].find(
    row => row.querySelector?.(".item-title")?.textContent === targetTitle
  );

  if (mode === "start") {
    await __pickerWaitFor(
      () =>
        state.selected?.id === targetId &&
        state.selectionSource === "thunderbird",
      "native Thunderbird selection adoption"
    );
    __pickerAssert(
      $("selected-title").textContent === targetTitle,
      "Task picker did not keep Thunderbird's native selected Task"
    );
    __pickerAssert($("current-strip").hidden, "Idle Task picker incorrectly shows a current Task");
    __pickerAssert(__pickerButton("开始这个 Task"), "Start action is missing from idle Task selection");
    __pickerAssert(!__pickerButton("换下当前 Task"), "Switch-away action appeared without a current Task");

    __pickerButton("开始这个 Task").click();
    await browser.runtime.sendMessage({
      kind: "thunderbird-caldav-picker-start-acceptance",
      result: {
        ok: true,
        segmentedUi: true,
        targetSelected: true,
        startClicked: true,
      },
    });
    return;
  }

  targetRow.click();
  __pickerAssert($("selected-title").textContent === targetTitle, "Selected Task title was not kept");

  __pickerAssert(!$("current-strip").hidden, "Switch picker did not show the current Task context");
  __pickerAssert(
    $("current-strip-text").textContent.includes("Seed task from Radicale"),
    "Switch picker lost the current Task context"
  );
  __pickerAssert(__pickerButton("换下当前 Task"), "Explicit switch-away step is missing");
  __pickerAssert(!__pickerButton("开始这个 Task"), "Start was offered before the current Task was put aside");

  const before = await AssistantStorage.getLastReceipt();
  __pickerButton("换下当前 Task").click();
  const receipt = await __pickerWaitForNewReceipt("switch-away", before?.id || null);
  await __pickerWaitFor(
    () =>
      state.runtime?.state === "idle" &&
      state.selected?.id === targetId &&
      Boolean(__pickerButton("开始这个 Task")),
    "switch-away -> preserved target selection"
  );

  __pickerAssert(receipt.logSaved === true, "Switch-away result was not persisted before continuing");
  __pickerAssert(
    $("selected-title").textContent === "Switch target task",
    "Target selection was lost after switching away from the current Task"
  );

  await browser.runtime.sendMessage({
    kind: "thunderbird-caldav-picker-switch-acceptance",
    result: {
      ok: true,
      switchAwayVerified: true,
      targetSelectionPreserved: true,
      explicitStartStep: true,
    },
  });

  __pickerButton("开始这个 Task").click();
}

setTimeout(() => {
  __runTaskPickerAcceptance().catch(error =>
    browser.runtime.sendMessage({
      kind: new URLSearchParams(location.search).get("acceptance") === "switch"
        ? "thunderbird-caldav-picker-switch-acceptance"
        : "thunderbird-caldav-picker-start-acceptance",
      result: {
        ok: false,
        error:
          (error?.message || String(error)) +
          (error?.stack ? "\n" + error.stack : ""),
      },
    })
  );
}, 800);
'''
with (root / "task-picker.js").open("a", encoding="utf-8") as handle:
    handle.write("\n" + task_picker_acceptance + "\n")

workspace_acceptance = r'''
async function __workspaceWaitFor(predicate, label, timeoutMs = 20000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error("Workspace timeout: " + label);
}

function __workspaceAssert(condition, message) {
  if (!condition) throw new Error(message);
}

function __workspaceButton(label) {
  return [...$("actions").querySelectorAll("button")].find(
    button => button.textContent === label
  );
}

async function __workspaceWaitForNewReceipt(action, previousId, timeoutMs = 15000) {
  let receipt = null;
  await __workspaceWaitFor(async () => {
    receipt = await AssistantStorage.getLastReceipt();
    return receipt?.id !== previousId && receipt?.action === action;
  }, "new receipt " + action, timeoutMs);
  __workspaceAssert(receipt?.success, action + " failed: " + (receipt?.error || receipt?.summary || ""));
  return receipt;
}

async function __runWorkspaceAcceptance() {
  const mode = new URLSearchParams(location.search).get("acceptance");
  if (!mode) return;

  const expectedTitle = mode === "complete" ? "Switch target task" : "Seed task from Radicale";
  await __workspaceWaitFor(
    () =>
      state.current?.title === expectedTitle &&
      $("current-title").textContent === expectedTitle,
    "current Task render"
  );

  __workspaceAssert(!document.getElementById("task-list"), "Task browser leaked back into the Work page");
  __workspaceAssert(!document.getElementById("task-view"), "Task filter leaked back into the Work page");
  __workspaceAssert(!document.getElementById("task-search"), "Task search leaked back into the Work page");
  __workspaceAssert(!document.getElementById("receipt"), "Detailed result log leaked back into the Work page");
  __workspaceAssert(
    $("task-picker-link").getAttribute("href") === "task-picker.html",
    "Work page does not link to the separate Task picker"
  );
  const navLabels = [...document.querySelectorAll(".tool-nav a")].map(node => node.textContent.trim());
  __workspaceAssert(
    JSON.stringify(navLabels) === JSON.stringify(["工作", "今天", "记录", "日志", "WordPress", "工具"]),
    "Work UI did not expose the six stable top-level pages including WordPress"
  );

  if (mode === "active") {
    __workspaceAssert(__workspaceButton("暂停"), "Pause is missing for the current working Task");
    __workspaceAssert(__workspaceButton("完成"), "Complete is missing for the current working Task");
    __workspaceAssert(__workspaceButton("取消"), "Cancel is missing for the current working Task");
    __workspaceAssert($("task-picker-link").textContent === "换 Task", "Current Work does not offer Task switching");

    let before = await AssistantStorage.getLastReceipt();
    __workspaceButton("暂停").click();
    let receipt = await __workspaceWaitForNewReceipt("pause", before?.id || null);
    await __workspaceWaitFor(
      () => state.runtime?.state === "paused" && Boolean(__workspaceButton("继续")),
      "Pause -> paused"
    );

    before = receipt;
    __workspaceButton("继续").click();
    receipt = await __workspaceWaitForNewReceipt("resume", before?.id || null);
    await __workspaceWaitFor(
      () => state.runtime?.state === "working" && Boolean(__workspaceButton("暂停")),
      "Resume -> working"
    );

    await browser.runtime.sendMessage({
      kind: "thunderbird-caldav-workspace-active-acceptance",
      result: {
        ok: true,
        segmentedUi: true,
        pauseResumeUi: true,
        persistentReceipt: receipt.logSaved === true,
      },
    });
    return;
  }

  __workspaceAssert(__workspaceButton("完成"), "Complete is missing for switched current Task");
  const before = await AssistantStorage.getLastReceipt();
  __workspaceButton("完成").click();
  const receipt = await __workspaceWaitForNewReceipt("complete", before?.id || null);
  await __workspaceWaitFor(
    () => state.runtime?.state === "idle" && !$("no-current").hidden,
    "Complete -> idle"
  );

  await browser.runtime.sendMessage({
    kind: "thunderbird-caldav-workspace-complete-acceptance",
    result: {
      ok: true,
      completeUi: true,
      persistentReceipt: receipt.logSaved === true,
    },
  });
}

setTimeout(() => {
  __runWorkspaceAcceptance().catch(error =>
    browser.runtime.sendMessage({
      kind: new URLSearchParams(location.search).get("acceptance") === "complete"
        ? "thunderbird-caldav-workspace-complete-acceptance"
        : "thunderbird-caldav-workspace-active-acceptance",
      result: {
        ok: false,
        error:
          (error?.message || String(error)) +
          (error?.stack ? "\n" + error.stack : ""),
      },
    })
  );
}, 800);
'''
with (root / "workspace.js").open("a", encoding="utf-8") as handle:
    handle.write("\n" + workspace_acceptance + "\n")

tools_acceptance = r'''
async function __toolsWaitFor(predicate, label, timeoutMs = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error("Tools timeout: " + label);
}

function __toolsAssert(condition, message) {
  if (!condition) throw new Error(message);
}

async function __runToolsAcceptance() {
  await __toolsWaitFor(
    () => [...$("task-calendar").options].some(option => option.value === "acceptance-calendar"),
    "Task Calendar options"
  );

  __toolsAssert(location.hash === "#task-defaults", "Assistant did not navigate to the Task defaults section");
  __toolsAssert(Boolean(document.getElementById("task-defaults")), "Task defaults section is missing");
  __toolsAssert($("task-view").value === "incomplete", "Default Task view is not Incomplete");
  __toolsAssert(
    [...$("task-calendar").options].some(option => option.value === "acceptance-calendar"),
    "Thunderbird Calendar list was not reused in Settings"
  );

  const before = await AssistantStorage.getSettings();
  const beforeDefaults = {
    taskView: before.taskView,
    taskCalendarId: before.taskCalendarId,
    workCalendarId: before.workCalendarId,
  };
  $("task-view").value = "completed";
  $("task-calendar").value = "acceptance-calendar";
  $("save-settings").click();

  await __toolsWaitFor(async () => {
    const settings = await AssistantStorage.getSettings();
    return settings.taskView === "completed" &&
      settings.taskCalendarId === "acceptance-calendar";
  }, "save Task defaults");

  __toolsAssert(!$("undo-settings").hidden, "Undo was not offered after changing defaults");
  $("undo-settings").click();

  await __toolsWaitFor(async () => {
    const settings = await AssistantStorage.getSettings();
    return settings.taskView === beforeDefaults.taskView &&
      settings.taskCalendarId === beforeDefaults.taskCalendarId &&
      settings.workCalendarId === beforeDefaults.workCalendarId;
  }, "undo Task defaults");

  return {
    ok: true,
    navigatedToSettings: true,
    thunderbirdCalendarsReused: true,
    settingsSaved: true,
    settingsUndone: true,
  };
}

setTimeout(() => {
  __runToolsAcceptance()
    .then(result =>
      browser.runtime.sendMessage({
        kind: "thunderbird-caldav-tools-acceptance",
        result,
      })
    )
    .catch(error =>
      browser.runtime.sendMessage({
        kind: "thunderbird-caldav-tools-acceptance",
        result: {
          ok: false,
          error:
            (error?.message || String(error)) +
            (error?.stack ? "\n" + error.stack : ""),
        },
      })
    );
}, 800);
'''
with (root / "tools.js").open("a", encoding="utf-8") as handle:
    handle.write("\n" + tools_acceptance + "\n")

logs_acceptance = r'''
async function __logsWaitFor(predicate, label, timeoutMs = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error("Logs timeout: " + label);
}

function __logsAssert(condition, message) {
  if (!condition) throw new Error(message);
}

async function __runLogsAcceptance() {
  await __logsWaitFor(
    async () => (await AssistantStorage.listAudit()).length > 0,
    "existing audit rows"
  );

  $("search").value = "__definitely_no_log_match__";
  $("search").dispatchEvent(new Event("input"));
  __logsAssert(
    $("logs").textContent === "当前筛选没有匹配的日志。",
    "Filtered-empty log state is ambiguous"
  );

  $("search").value = "";
  $("search").dispatchEvent(new Event("input"));
  $("clear").click();
  __logsAssert(!$("clear-confirm").hidden, "Clear confirmation did not open");
  __logsAssert($("logs").hidden, "Log result area remained visible behind clear confirmation");

  $("clear-no").click();
  __logsAssert($("clear-confirm").hidden, "Clear confirmation did not close on Back");
  __logsAssert(!$("logs").hidden, "Log list did not return after cancelling clear");

  $("clear").click();
  $("clear-yes").click();
  await __logsWaitFor(
    async () => (await AssistantStorage.listAudit()).length === 0,
    "audit clear persistence"
  );
  await __logsWaitFor(
    () =>
      $("clear-confirm").hidden &&
      $("log-status").textContent === "✓ 操作日志已清空。" &&
      $("logs").textContent === "尚无操作日志。",
    "clear UI settled after persistent removal"
  );
  __logsAssert($("clear-confirm").hidden, "Clear confirmation remained visible after clear");
  __logsAssert(
    $("log-status").textContent === "✓ 操作日志已清空。",
    "Successful clear status was not shown"
  );
  __logsAssert(
    $("logs").textContent === "尚无操作日志。",
    "Cleared log list did not show the true empty state"
  );

  return {
    ok: true,
    filteredEmptyDistinct: true,
    confirmationExclusive: true,
    cancelRestoresList: true,
    clearPersistent: true,
    emptyStateCorrect: true,
  };
}

setTimeout(() => {
  __runLogsAcceptance()
    .then(result =>
      browser.runtime.sendMessage({
        kind: "thunderbird-caldav-logs-acceptance",
        result,
      })
    )
    .catch(error =>
      browser.runtime.sendMessage({
        kind: "thunderbird-caldav-logs-acceptance",
        result: {
          ok: false,
          error:
            (error?.message || String(error)) +
            (error?.stack ? "\n" + error.stack : ""),
        },
      })
    );
}, 800);
'''
with (root / "logs.js").open("a", encoding="utf-8") as handle:
    handle.write("\n" + logs_acceptance + "\n")

acceptance = r'''
const __ACCEPTANCE_REPORT = "http://127.0.0.1:8765/report";
let __acceptanceStage = "startup";
let __pickerStartAcceptanceResolve;
const __pickerStartAcceptancePromise = new Promise(resolve => {
  __pickerStartAcceptanceResolve = resolve;
});
let __workspaceActiveAcceptanceResolve;
const __workspaceActiveAcceptancePromise = new Promise(resolve => {
  __workspaceActiveAcceptanceResolve = resolve;
});
let __pickerSwitchAcceptanceResolve;
const __pickerSwitchAcceptancePromise = new Promise(resolve => {
  __pickerSwitchAcceptanceResolve = resolve;
});
let __workspaceCompleteAcceptanceResolve;
const __workspaceCompleteAcceptancePromise = new Promise(resolve => {
  __workspaceCompleteAcceptanceResolve = resolve;
});
let __toolsAcceptanceResolve;
const __toolsAcceptancePromise = new Promise(resolve => {
  __toolsAcceptanceResolve = resolve;
});
let __logsAcceptanceResolve;
const __logsAcceptancePromise = new Promise(resolve => {
  __logsAcceptanceResolve = resolve;
});
browser.runtime.onMessage.addListener(message => {
  if (message?.kind === "thunderbird-caldav-picker-start-acceptance") {
    __pickerStartAcceptanceResolve(message.result);
  }
  if (message?.kind === "thunderbird-caldav-workspace-active-acceptance") {
    __workspaceActiveAcceptanceResolve(message.result);
  }
  if (message?.kind === "thunderbird-caldav-picker-switch-acceptance") {
    __pickerSwitchAcceptanceResolve(message.result);
  }
  if (message?.kind === "thunderbird-caldav-workspace-complete-acceptance") {
    __workspaceCompleteAcceptanceResolve(message.result);
  }
  if (message?.kind === "thunderbird-caldav-tools-acceptance") {
    __toolsAcceptanceResolve(message.result);
  }
  if (message?.kind === "thunderbird-caldav-logs-acceptance") {
    __logsAcceptanceResolve(message.result);
  }
});

function __acceptanceAssert(condition, message) {
  if (!condition) throw new Error(message);
}

function __acceptanceDelay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function __acceptanceIcalEquals(actual, expected) {
  return String(actual || "").replace(/Z$/, "") === expected;
}

async function __acceptanceReport(payload) {
  await fetch(__ACCEPTANCE_REPORT, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
}

async function __waitForAcceptanceCalendar() {
  for (let attempt = 0; attempt < 120; attempt++) {
    const calendars = await browser.ThunderbirdCalDAV.listCalendars();
    const calendar = calendars.find(item => item.id === "acceptance-calendar");
    if (calendar && !calendar.disabled) {
      const tasks = await browser.ThunderbirdCalDAV.listTasks(calendar.id);
      if (tasks.some(task => task.id === "seed-task")) {
        return calendar;
      }
    }
    await __acceptanceDelay(250);
  }
  throw new Error("Timed out waiting for Thunderbird CalDAV provider to load seed VTODO");
}

async function __runRealAcceptance() {
  __acceptanceStage = "spaces-query";
  const spaces = await browser.spaces.query({
    isSelfOwned: true,
    name: "thunderbird_caldav_lab",
  });
  __acceptanceAssert(spaces.length === 1, "Thunderbird CalDAV Space was not created");

  __acceptanceStage = "wait-calendar-seed";
  const calendar = await __waitForAcceptanceCalendar();

  __acceptanceStage = "native-task-selector-recurring-anki";
  let nativeAnki = [];
  for (let attempt = 0; attempt < 120; attempt++) {
    nativeAnki = await browser.ThunderbirdCalDAV.listNativeTasks({
      filter: "open",
      searchText: "Anki",
    });
    if (
      nativeAnki.some(
        task =>
          task.id === "anki-recurring" &&
          task.title === "Anki" &&
          Boolean(task.recurrenceId)
      )
    ) {
      break;
    }
    if (attempt === 119) {
      throw new Error(
        "Thunderbird native Task selector did not expose recurring Anki occurrence"
      );
    }
    await __acceptanceDelay(100);
  }

  __acceptanceStage = "native-calendar-selector";
  await browser.ThunderbirdCalDAV.setCalendarDisplayed(calendar.id, false);
  const hiddenNativeTasks = await browser.ThunderbirdCalDAV.listNativeTasks({
    filter: "open",
    searchText: "Seed task from Radicale",
  });
  __acceptanceAssert(
    !hiddenNativeTasks.some(task => task.id === "seed-task"),
    "Hidden Thunderbird Calendar still leaked into native Task selector"
  );
  await browser.ThunderbirdCalDAV.setCalendarDisplayed(calendar.id, true);
  const restoredNativeTasks = await browser.ThunderbirdCalDAV.listNativeTasks({
    filter: "open",
    searchText: "Seed task from Radicale",
  });
  __acceptanceAssert(
    restoredNativeTasks.some(task => task.id === "seed-task"),
    "Restored Thunderbird Calendar did not return to native Task selector"
  );

  __acceptanceStage = "native-task-selection-bridge";
  const selectedNative = await browser.AcceptanceTaskFix.selectTaskByTitle(
    "Seed task from Radicale"
  );
  __acceptanceAssert(
    selectedNative?.ok && selectedNative.id === "seed-task",
    "Could not select the seed Task in Thunderbird's native Tasks tree"
  );
  let bridgedSelection = [];
  for (let attempt = 0; attempt < 40; attempt++) {
    bridgedSelection = await browser.TaskFix.getSelectedTasks();
    if (
      bridgedSelection.length === 1 &&
      bridgedSelection[0].id === "seed-task" &&
      bridgedSelection[0].calendarId === calendar.id
    ) {
      break;
    }
    await __acceptanceDelay(100);
  }
  __acceptanceAssert(
    bridgedSelection.length === 1 && bridgedSelection[0].id === "seed-task",
    "CalDAV Assistant did not read Thunderbird's native selected Task"
  );

  __acceptanceStage = "task-picker-start";
  const pickerStartTab = await browser.tabs.create({
    url: browser.runtime.getURL("task-picker.html?acceptance=start"),
  });
  __acceptanceAssert(Boolean(pickerStartTab?.id), "Task picker tab could not be opened");
  const pickerStartResult = await Promise.race([
    __pickerStartAcceptancePromise,
    __acceptanceDelay(30000).then(() => {
      throw new Error("Timed out waiting for Task picker Start acceptance");
    }),
  ]);
  __acceptanceAssert(
    pickerStartResult?.ok,
    "Task picker Start acceptance failed: " + (pickerStartResult?.error || "unknown")
  );
  __acceptanceAssert(pickerStartResult.segmentedUi, "Task picker segmented UI contract failed");

  for (let attempt = 0; attempt < 160; attempt++) {
    const runtimeState = await browser.storage.local.get("caldavAssistant.runtime");
    const runtime = runtimeState["caldavAssistant.runtime"];
    if (runtime?.state === "working" && runtime?.currentTask?.id === "seed-task") break;
    if (attempt === 159) throw new Error("Task picker Start did not make seed-task current");
    await __acceptanceDelay(100);
  }
  await browser.tabs.remove(pickerStartTab.id);

  __acceptanceStage = "workspace-active";
  const workspaceTab = await browser.tabs.create({
    url: browser.runtime.getURL("workspace.html?acceptance=active"),
  });
  __acceptanceAssert(Boolean(workspaceTab?.id), "Workspace tab could not be opened");
  const workspaceActiveResult = await Promise.race([
    __workspaceActiveAcceptancePromise,
    __acceptanceDelay(45000).then(() => {
      throw new Error("Timed out waiting for active Work UI acceptance");
    }),
  ]);
  __acceptanceAssert(
    workspaceActiveResult?.ok,
    "Active Work UI acceptance failed: " + (workspaceActiveResult?.error || "unknown")
  );
  __acceptanceAssert(workspaceActiveResult.segmentedUi, "Work page is not segmented");
  __acceptanceAssert(workspaceActiveResult.pauseResumeUi, "Pause/Resume human path did not pass");
  __acceptanceAssert(workspaceActiveResult.persistentReceipt, "Pause/Resume receipt persistence failed");
  await browser.tabs.remove(workspaceTab.id);

  __acceptanceStage = "create-switch-target";
  const switchTarget = await browser.ThunderbirdCalDAV.createTask(calendar.id, {
    title: "Switch target task",
    status: "NEEDS-ACTION",
    percentComplete: 0,
    categories: ["Acceptance"],
  });
  __acceptanceAssert(switchTarget?.id, "Created switch target has no provider UID");
  await browser.storage.local.set({
    "caldavAssistant.acceptanceSwitchTarget": {
      id: switchTarget.id,
      calendarId: switchTarget.calendarId || calendar.id,
      title: switchTarget.title || "Switch target task",
    },
  });
  for (let attempt = 0; attempt < 120; attempt++) {
    const available = await browser.ThunderbirdCalDAV.listTasks(calendar.id);
    if (available.some(task => task.id === switchTarget.id)) break;
    if (attempt === 119) throw new Error("Created switch target did not become visible through listTasks");
    await __acceptanceDelay(100);
  }

  __acceptanceStage = "task-picker-switch";
  const pickerSwitchTab = await browser.tabs.create({
    url: browser.runtime.getURL("task-picker.html?acceptance=switch"),
  });
  __acceptanceAssert(Boolean(pickerSwitchTab?.id), "Switch Task picker tab could not be opened");
  const pickerSwitchResult = await Promise.race([
    __pickerSwitchAcceptancePromise,
    __acceptanceDelay(45000).then(() => {
      throw new Error("Timed out waiting for Task picker switch acceptance");
    }),
  ]);
  __acceptanceAssert(
    pickerSwitchResult?.ok,
    "Task picker switch acceptance failed: " + (pickerSwitchResult?.error || "unknown")
  );
  __acceptanceAssert(pickerSwitchResult.switchAwayVerified, "Switch-away human path did not pass");
  __acceptanceAssert(
    pickerSwitchResult.targetSelectionPreserved,
    "Target selection was not preserved across the switch-away step"
  );
  __acceptanceAssert(pickerSwitchResult.explicitStartStep, "Switch flow auto-chained instead of staying segmented");

  for (let attempt = 0; attempt < 160; attempt++) {
    const runtimeState = await browser.storage.local.get("caldavAssistant.runtime");
    const runtime = runtimeState["caldavAssistant.runtime"];
    if (runtime?.state === "working" && runtime?.currentTask?.id === switchTarget.id) break;
    if (attempt === 159) throw new Error("Explicit Start did not make the selected switch target current");
    await __acceptanceDelay(100);
  }
  await browser.tabs.remove(pickerSwitchTab.id);

  __acceptanceStage = "workspace-complete";
  const workspaceCompleteTab = await browser.tabs.create({
    url: browser.runtime.getURL("workspace.html?acceptance=complete"),
  });
  __acceptanceAssert(Boolean(workspaceCompleteTab?.id), "Complete Workspace tab could not be opened");
  const workspaceCompleteResult = await Promise.race([
    __workspaceCompleteAcceptancePromise,
    __acceptanceDelay(30000).then(() => {
      throw new Error("Timed out waiting for switched Task Complete acceptance");
    }),
  ]);
  __acceptanceAssert(
    workspaceCompleteResult?.ok,
    "Switched Task Complete acceptance failed: " + (workspaceCompleteResult?.error || "unknown")
  );
  __acceptanceAssert(workspaceCompleteResult.completeUi, "Complete human path did not pass");
  __acceptanceAssert(workspaceCompleteResult.persistentReceipt, "Complete receipt persistence failed");
  await browser.tabs.remove(workspaceCompleteTab.id);

  __acceptanceStage = "tools-guided-settings";
  const toolsTab = await browser.tabs.create({
    url: browser.runtime.getURL("tools.html#task-defaults"),
  });
  __acceptanceAssert(Boolean(toolsTab?.id), "Tools tab could not be opened");
  const toolsResult = await Promise.race([
    __toolsAcceptancePromise,
    __acceptanceDelay(30000).then(() => {
      throw new Error("Timed out waiting for Tools guided-settings acceptance");
    }),
  ]);
  __acceptanceAssert(
    toolsResult?.ok,
    "Tools guided-settings acceptance failed: " + (toolsResult?.error || "unknown")
  );
  __acceptanceAssert(toolsResult.navigatedToSettings, "Assistant did not land on Task defaults");
  __acceptanceAssert(toolsResult.thunderbirdCalendarsReused, "Settings did not reuse Thunderbird Calendars");
  __acceptanceAssert(toolsResult.settingsSaved, "Task defaults did not save");
  __acceptanceAssert(toolsResult.settingsUndone, "Task defaults could not be undone");
  await browser.tabs.remove(toolsTab.id);

  __acceptanceStage = "taskfix-real-ui";
  const taskFix = await browser.AcceptanceTaskFix.openTasksAndCheck();
  __acceptanceAssert(
    taskFix?.ok,
    "TaskFix real Tasks UI injection failed: " + JSON.stringify(taskFix)
  );
  __acceptanceAssert(taskFix.statusButton, "TaskFix Status toolbar button is missing");
  __acceptanceAssert(taskFix.contextStatus, "TaskFix Status context menu is missing");

  __acceptanceStage = "diagnostics";
  await browser.ThunderbirdCalDAV.writeDiagnostic("acceptance", "probe", {
    password: "must-not-leak",
    note: "diagnostics-probe-ok",
  });
  const diagnosticInfo = await browser.ThunderbirdCalDAV.diagnosticsInfo();
  const diagnosticRead = await browser.ThunderbirdCalDAV.readDiagnostics(400);
  __acceptanceAssert(Boolean(diagnosticInfo.path), "Diagnostics path is missing");
  __acceptanceAssert(
    diagnosticRead.text.includes('"component":"acceptance"') &&
      diagnosticRead.text.includes('"event":"probe"'),
    "Persistent diagnostics probe was not readable"
  );
  __acceptanceAssert(
    !diagnosticRead.text.includes("must-not-leak"),
    "Diagnostics did not redact a password field"
  );

  __acceptanceStage = "recheck-calendar-seed";
  await __waitForAcceptanceCalendar();
  __acceptanceAssert(calendar.type === "caldav", "Configured calendar is not CalDAV");
  __acceptanceAssert(!calendar.readOnly, "Configured CalDAV calendar became read-only");
  __acceptanceAssert(calendar.supportsTasks, "CalDAV calendar does not support VTODO");
  __acceptanceAssert(calendar.supportsEvents, "CalDAV calendar does not support VEVENT");

  __acceptanceStage = "list-seed-task";
  let tasks = await browser.ThunderbirdCalDAV.listTasks(calendar.id);
  __acceptanceAssert(
    tasks.some(task => task.id === "seed-task" && task.title === "Seed task from Radicale"),
    "Seed VTODO was not read through Thunderbird"
  );

  __acceptanceStage = "verify-workflow-task";
  let workflowTask = await browser.ThunderbirdCalDAV.getTask(calendar.id, "seed-task");
  __acceptanceAssert(workflowTask.status === "NEEDS-ACTION", "Switch-away did not restore seed Task to its pre-start incomplete status");
  __acceptanceAssert(workflowTask.paused === false, "Switch-away incorrectly left seed Task paused/resumable");

  const switchedTask = await browser.ThunderbirdCalDAV.getTask(calendar.id, switchTarget.id);
  __acceptanceAssert(switchedTask.status === "COMPLETED", "Switched Task Complete was not persisted to CalDAV");
  __acceptanceAssert(switchedTask.paused === false, "Completed switched Task retained paused marker");

  __acceptanceStage = "verify-work-sessions";
  const seedWorkEvents = (await browser.ThunderbirdCalDAV.listEvents(calendar.id, "", "")).filter(
    item => item.workSession && item.taskUid === "seed-task"
  );
  const switchWorkEvents = (await browser.ThunderbirdCalDAV.listEvents(calendar.id, "", "")).filter(
    item => item.workSession && item.taskUid === switchTarget.id
  );
  __acceptanceAssert(seedWorkEvents.length >= 2, "Start/Resume did not create separate seed Work VEVENTs");
  __acceptanceAssert(
    seedWorkEvents.every(item => item.end && !item.workOpen),
    "Switch-away left a seed Work VEVENT open"
  );
  __acceptanceAssert(switchWorkEvents.length >= 1, "Switched Task Start did not create a Work VEVENT");
  __acceptanceAssert(
    switchWorkEvents.every(item => item.end && !item.workOpen),
    "Switched Task Complete left a Work VEVENT open"
  );
  let workEvents = [...seedWorkEvents, ...switchWorkEvents];

  __acceptanceStage = "verify-workflow-audit";
  const auditRows = await AssistantStorage.listAudit();
  const workflowActions = auditRows
    .filter(row => row.scope === "workflow")
    .map(row => row.action);
  for (const expected of ["start", "pause", "resume", "switch-away", "complete"]) {
    __acceptanceAssert(workflowActions.includes(expected), "Persistent audit missing " + expected);
  }

  __acceptanceStage = "task-write-readback";
  await browser.ThunderbirdCalDAV.updateTask(calendar.id, "seed-task", {
    status: "IN-PROCESS",
    paused: true,
    percentComplete: 40,
  });
  let taskReadback = await browser.ThunderbirdCalDAV.getTask(calendar.id, "seed-task");
  __acceptanceAssert(taskReadback.status === "IN-PROCESS", "Existing Task status write/readback failed");
  __acceptanceAssert(taskReadback.paused === true, "Existing Task paused write/readback failed");
  __acceptanceAssert(taskReadback.percentComplete === 40, "Existing Task progress write/readback failed");

  __acceptanceStage = "create-event";
  const event = await browser.ThunderbirdCalDAV.createEvent(calendar.id, {
    title: "Runtime Event",
    start: "2026-10-05T09:00",
    end: "2026-10-05T10:00",
    categories: ["Acceptance"],
    description: "Created by real Thunderbird 153 acceptance",
  });
  __acceptanceAssert(event.id, "Created event has no UID");

  __acceptanceStage = "list-event";
  let events = await browser.ThunderbirdCalDAV.listEvents(
    calendar.id,
    "2026-10-05",
    "2026-10-06"
  );
  __acceptanceAssert(
    events.some(item => item.id === event.id),
    "Created VEVENT was not re-read from Thunderbird"
  );

  __acceptanceStage = "update-event";
  const updatedEvent = await browser.ThunderbirdCalDAV.updateEvent(calendar.id, event.id, {
    title: "Runtime Event Updated",
    start: "2026-10-05T11:00",
    end: "2026-10-05T12:30",
    categories: ["Acceptance", "Updated"],
    description: "Updated through Thunderbird calendar provider",
  });
  __acceptanceAssert(updatedEvent.title === "Runtime Event Updated", "Event title update failed");
  __acceptanceAssert(
    __acceptanceIcalEquals(updatedEvent.start?.icalString, "20261005T110000"),
    `Event start update failed: ${updatedEvent.start?.icalString}; source=${updatedEvent.start?.sourceIcalString}`
  );

  __acceptanceStage = "invalid-event-validation";
  let rejected = false;
  try {
    await browser.ThunderbirdCalDAV.updateEvent(calendar.id, event.id, {
      start: "2026-10-05T14:00",
      end: "2026-10-05T13:00",
    });
  } catch (error) {
    rejected = /end must not be before/i.test(error?.message || String(error));
  }
  __acceptanceAssert(rejected, "Invalid backwards event was not rejected");

  __acceptanceStage = "cleanup-test-data";
  await browser.ThunderbirdCalDAV.deleteEvent(calendar.id, event.id);
  for (const workEvent of workEvents) {
    await browser.ThunderbirdCalDAV.deleteEvent(calendar.id, workEvent.id);
  }
  await browser.ThunderbirdCalDAV.deleteTask(calendar.id, switchTarget.id);
  await browser.storage.local.set({"caldavAssistant.acceptanceSwitchTarget": null});
  await browser.ThunderbirdCalDAV.updateTask(calendar.id, "seed-task", {
    status: "NEEDS-ACTION",
    paused: false,
    percentComplete: 0,
  });

  tasks = await browser.ThunderbirdCalDAV.listTasks(calendar.id);
  events = await browser.ThunderbirdCalDAV.listEvents(calendar.id, "", "");
  const restoredSeed = tasks.find(task => task.id === "seed-task");
  const recurringAnkiParent = tasks.find(task => task.id === "anki-recurring");
  __acceptanceAssert(
    tasks.length === 2 &&
      restoredSeed?.status === "NEEDS-ACTION" &&
      restoredSeed?.paused === false &&
      recurringAnkiParent?.title === "Anki",
    "Seed/recurring Anki fixtures were not restored after acceptance"
  );
  __acceptanceAssert(events.length === 0, "Acceptance left VEVENT test data behind");

  __acceptanceStage = "logs-clear-ui";
  const logsTab = await browser.tabs.create({
    url: browser.runtime.getURL("logs.html"),
  });
  __acceptanceAssert(Boolean(logsTab?.id), "Logs tab could not be opened");
  const logsResult = await Promise.race([
    __logsAcceptancePromise,
    __acceptanceDelay(30000).then(() => {
      throw new Error("Timed out waiting for Logs clear acceptance");
    }),
  ]);
  __acceptanceAssert(
    logsResult?.ok,
    "Logs clear UI acceptance failed: " + (logsResult?.error || "unknown")
  );
  __acceptanceAssert(logsResult.filteredEmptyDistinct, "Filtered empty-state contract failed");
  __acceptanceAssert(logsResult.confirmationExclusive, "Clear confirmation overlapped log empty state");
  __acceptanceAssert(logsResult.cancelRestoresList, "Clear cancel did not restore log list");
  __acceptanceAssert(logsResult.clearPersistent, "Log clear was not persistent");
  __acceptanceAssert(logsResult.emptyStateCorrect, "Cleared log empty state is incorrect");
  await browser.tabs.remove(logsTab.id);

  return {
    ok: true,
    thunderbirdCalDAV: true,
    calendar,
    seedTaskRead: true,
    taskWriteReadback: true,
    eventCrud: true,
    validation: true,
    workSessionLifecycle: true,
    persistentAudit: true,
    spaceCreated: true,
    workspaceOpened: true,
    workflowUi: true,
    persistentReceipt: true,
    simpleUi: true,
    segmentedUi: true,
    taskSwitchUi: true,
    taskFixRealUi: true,
    diagnostics: true,
    logsClearUi: true,
    createdEventId: event.id,
  };
}

setTimeout(() => {
  __runRealAcceptance()
    .then(result => __acceptanceReport(result))
    .catch(async error => {
      console.error("[ThunderbirdCalDAV acceptance]", error);
      try {
        await __acceptanceReport({
          ok: false,
          stage: __acceptanceStage,
          name: error?.name || "",
          message: error?.message || String(error),
          error: error?.stack || error?.message || String(error),
        });
      } catch (reportError) {
        console.error("[ThunderbirdCalDAV acceptance report]", reportError);
      }
    });
}, 1500);
'''
with (root / "background.js").open("a", encoding="utf-8") as handle:
    handle.write("\n" + acceptance + "\n")
PY

(
  cd "$TMP/addon"
  zip -qr "$TMP/acceptance.xpi" .
)

echo "== Start Radicale =="
cat >"$TMP/users" <<'EOF'
acceptance:test-password
EOF
cat >"$TMP/rights" <<'EOF'
[acceptance]
user: ^acceptance$
collection: ^acceptance(/.*)?$
permissions: RrWw
EOF
cat >"$TMP/radicale.conf" <<EOF
[server]
hosts = 127.0.0.1:5232

[auth]
type = htpasswd
htpasswd_filename = $TMP/users
htpasswd_encryption = plain
realm = acceptance-realm
delay = 0

[rights]
type = from_file
file = $TMP/rights

[storage]
filesystem_folder = $TMP/storage

[logging]
level = debug
EOF
python3 -m radicale --config "$TMP/radicale.conf" >"$TMP/radicale.log" 2>&1 &
RADICALE_PID=$!

for _ in $(seq 1 80); do
  if curl -fsS -u acceptance:test-password http://127.0.0.1:5232/ >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
curl -fsS -u acceptance:test-password http://127.0.0.1:5232/ >/dev/null

echo "== Create real CalDAV collection and seed VTODO =="
cat >"$TMP/mkcalendar.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<C:mkcalendar xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:set>
    <D:prop>
      <D:displayname>Acceptance</D:displayname>
      <C:supported-calendar-component-set>
        <C:comp name="VEVENT"/>
        <C:comp name="VTODO"/>
      </C:supported-calendar-component-set>
    </D:prop>
  </D:set>
</C:mkcalendar>
EOF
status="$(curl -sS -o "$TMP/mkcalendar.out" -w '%{http_code}'   -X MKCALENDAR   -H 'Content-Type: application/xml; charset=utf-8'   --data-binary @"$TMP/mkcalendar.xml"   -u acceptance:test-password   http://127.0.0.1:5232/acceptance/test/)"
if [[ "$status" != "201" && "$status" != "200" ]]; then
  echo "MKCALENDAR failed: HTTP $status"
  cat "$TMP/mkcalendar.out"
  cat "$TMP/radicale.log"
  exit 1
fi

cat >"$TMP/seed.ics" <<'EOF'
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Thunderbird CalDAV Lab Acceptance//EN
BEGIN:VTODO
UID:seed-task
DTSTAMP:20260930T000000Z
SUMMARY:Seed task from Radicale
STATUS:NEEDS-ACTION
DUE:20261005T100000Z
END:VTODO
END:VCALENDAR
EOF
curl -fsS -X PUT   -H 'Content-Type: text/calendar; charset=utf-8'   --data-binary @"$TMP/seed.ics"   -u acceptance:test-password   http://127.0.0.1:5232/acceptance/test/seed-task.ics >/dev/null

# Regression fixture for the real user-visible failure: a recurring VTODO named
# exactly "Anki" must be found through Thunderbird's native Task selector.
cat >"$TMP/anki-recurring.ics" <<'EOF'
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Thunderbird CalDAV Lab Acceptance//EN
BEGIN:VTODO
UID:anki-recurring
DTSTAMP:20260930T000000Z
SUMMARY:Anki
DTSTART:20260930T120000Z
DUE:20260930T130000Z
RRULE:FREQ=DAILY;COUNT=10
STATUS:NEEDS-ACTION
END:VTODO
END:VCALENDAR
EOF
curl -fsS -X PUT   -H 'Content-Type: text/calendar; charset=utf-8'   --data-binary @"$TMP/anki-recurring.ics"   -u acceptance:test-password   http://127.0.0.1:5232/acceptance/test/anki-recurring.ics >/dev/null

echo "== Start acceptance report endpoint =="
cat >"$TMP/report_server.py" <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys

output = Path(sys.argv[1])

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        output.write_bytes(data)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
    def log_message(self, fmt, *args):
        pass

HTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
PY
python3 "$TMP/report_server.py" "$TMP/report.json" >"$TMP/report-server.log" 2>&1 &
REPORT_PID=$!

echo "== Download official Thunderbird $TB_VERSION =="
ARCHIVE="$TMP/thunderbird.tar.xz"
URL="https://archive.mozilla.org/pub/thunderbird/releases/$TB_VERSION/linux-x86_64/en-US/thunderbird-$TB_VERSION.tar.xz"
curl -fL --retry 3 --retry-delay 2 "$URL" -o "$ARCHIVE"
tar -xJf "$ARCHIVE" -C "$TMP"
"$TMP/thunderbird/thunderbird" --version

echo "== Prepare isolated Thunderbird profile =="
PROFILE="$TMP/profile"
mkdir -p "$PROFILE/extensions"
EXT_ID='ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net'
cp "$TMP/acceptance.xpi" "$PROFILE/extensions/$EXT_ID.xpi"

cat >"$PROFILE/user.js" <<'EOF'
user_pref("app.update.enabled", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("extensions.autoDisableScopes", 0);
user_pref("extensions.enabledScopes", 15);
user_pref("extensions.installDistroAddons", true);
user_pref("xpinstall.signatures.required", false);
user_pref("mail.provider.suppress_dialog_on_startup", true);
user_pref("mail.spotlight.firstRunDone", true);
user_pref("mail.winsearch.firstRunDone", true);
user_pref("mailnews.start_page.override_url", "about:blank");
user_pref("mailnews.start_page.url", "about:blank");
user_pref("calendar.item.promptDelete", false);
user_pref("calendar.timezone.useSystemTimezone", false);
user_pref("calendar.registry.acceptance-calendar.calendar-main-default", true);
user_pref("calendar.registry.acceptance-calendar.calendar-main-in-composite", true);
user_pref("calendar.registry.acceptance-calendar.cache.enabled", true);
user_pref("calendar.registry.acceptance-calendar.name", "Acceptance");
user_pref("calendar.registry.acceptance-calendar.type", "caldav");
user_pref("calendar.registry.acceptance-calendar.uri", "http://acceptance:test-password@127.0.0.1:5232/acceptance/test/");
user_pref("calendar.registry.acceptance-calendar.username", "acceptance");
user_pref("calendar.list.sortOrder", "acceptance-calendar");
EOF
printf 'user_pref("calendar.timezone.local", "%s");\n' "$TB_TIMEZONE" >>"$PROFILE/user.js"

echo "== Start Xvfb =="
Xvfb :99 -screen 0 1280x1024x24 >"$TMP/xvfb.log" 2>&1 &
XVFB_PID=$!
export DISPLAY=:99
sleep 0.5
if ! kill -0 "$XVFB_PID" 2>/dev/null; then
  echo "Xvfb failed to start."
  cat "$TMP/xvfb.log" || true
  exit 1
fi

echo "== Launch real Thunderbird $TB_VERSION ($TB_TIMEZONE) with the XPI =="
set +e
"$TMP/thunderbird/thunderbird" \
  -no-remote \
  -profile "$PROFILE" \
  >"$TMP/thunderbird.stdout" 2>"$TMP/thunderbird.stderr" &
TB_PID=$!
set -e

for _ in $(seq 1 240); do
  if [[ -s "$TMP/report.json" ]]; then
    break
  fi
  if ! kill -0 "$TB_PID" 2>/dev/null; then
    echo "Thunderbird exited before acceptance completed."
    cat "$TMP/thunderbird.stdout" || true
    cat "$TMP/thunderbird.stderr" || true
    exit 1
  fi
  sleep 0.25
done

if [[ ! -s "$TMP/report.json" ]]; then
  echo "Timed out waiting for real Thunderbird acceptance result."
  echo "--- Thunderbird stdout ---"
  cat "$TMP/thunderbird.stdout" || true
  echo "--- Thunderbird stderr ---"
  cat "$TMP/thunderbird.stderr" || true
  echo "--- Radicale log ---"
  cat "$TMP/radicale.log" || true
  exit 1
fi

echo "== Real Thunderbird result =="
cat "$TMP/report.json"
if ! python3 - "$TMP/report.json" <<'PY'
from pathlib import Path
import json
import sys

data = json.loads(Path(sys.argv[1]).read_text())
if not data.get("ok"):
    raise SystemExit(
        "Real Thunderbird acceptance failed at "
        + data.get("stage", "unknown")
        + ": "
        + data.get("error", data.get("message", "unknown error"))
    )
for key in (
    "thunderbirdCalDAV",
    "seedTaskRead",
    "taskWriteReadback",
    "eventCrud",
    "validation",
    "workSessionLifecycle",
    "persistentAudit",
    "spaceCreated",
    "workspaceOpened",
    "workflowUi",
    "persistentReceipt",
    "simpleUi",
    "taskFixRealUi",
    "diagnostics",
    "logsClearUi",
):
    assert data.get(key) is True, (key, data)
assert data["calendar"]["type"] == "caldav", data
print("real-thunderbird-caldav: PASS")
PY
then
  echo "--- Thunderbird stdout ---"
  cat "$TMP/thunderbird.stdout" || true
  echo "--- Thunderbird stderr ---"
  cat "$TMP/thunderbird.stderr" || true
  echo "--- Radicale log ---"
  cat "$TMP/radicale.log" || true
  exit 1
fi

echo "== Verify persistent CalDAV Assistant diagnostics =="
ASSISTANT_LOG="$(find "$PROFILE" -maxdepth 1 -type f -name 'caldav-assistant-experimental-*.log' -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
test -n "$ASSISTANT_LOG"
test -s "$ASSISTANT_LOG"
grep -q '"component":"acceptance"' "$ASSISTANT_LOG"
grep -q '"event":"probe"' "$ASSISTANT_LOG"
grep -q '"event":"task.update.success"' "$ASSISTANT_LOG"
grep -q '"event":"event.create.success"' "$ASSISTANT_LOG"
if grep -q 'must-not-leak\|test-password' "$ASSISTANT_LOG"; then
  echo "Sensitive value leaked into diagnostics log"
  cat "$ASSISTANT_LOG"
  exit 1
fi
echo "persistent-diagnostics: PASS ($ASSISTANT_LOG)"

echo "== Verify server state after Thunderbird CRUD =="
curl -fsS -u acceptance:test-password -X PROPFIND -H 'Depth: 1' \
  http://127.0.0.1:5232/acceptance/test/ >"$TMP/propfind.xml"
python3 - "$TMP/propfind.xml" <<'PY'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

root = ET.fromstring(Path(sys.argv[1]).read_bytes())
hrefs = [
    (node.text or "").strip()
    for node in root.findall(".//{DAV:}href")
    if (node.text or "").strip().endswith(".ics")
]
assert sorted(hrefs) == ["/acceptance/test/anki-recurring.ics", "/acceptance/test/seed-task.ics"], hrefs
print("radicale-clean-after-crud: PASS")
PY

echo "== Restart the same Thunderbird profile and repeat acceptance =="
kill "$TB_PID" 2>/dev/null || true
wait "$TB_PID" 2>/dev/null || true
TB_PID=""
rm -f "$TMP/report.json"
sleep 1

set +e
"$TMP/thunderbird/thunderbird" \
  -no-remote \
  -profile "$PROFILE" \
  >"$TMP/thunderbird-restart.stdout" 2>"$TMP/thunderbird-restart.stderr" &
TB_PID=$!
set -e

for _ in $(seq 1 260); do
  if [[ -s "$TMP/report.json" ]]; then
    break
  fi
  if ! kill -0 "$TB_PID" 2>/dev/null; then
    echo "Thunderbird exited during restart acceptance."
    cat "$TMP/thunderbird-restart.stdout" || true
    cat "$TMP/thunderbird-restart.stderr" || true
    exit 1
  fi
  sleep 0.25
done

if [[ ! -s "$TMP/report.json" ]]; then
  echo "Timed out waiting for restart acceptance result."
  cat "$TMP/thunderbird-restart.stdout" || true
  cat "$TMP/thunderbird-restart.stderr" || true
  cat "$TMP/radicale.log" || true
  exit 1
fi

echo "== Restart acceptance result =="
cat "$TMP/report.json"
python3 - "$TMP/report.json" <<'PY'
from pathlib import Path
import json
import sys

data = json.loads(Path(sys.argv[1]).read_text())
assert data.get("ok") is True, data
for key in (
    "thunderbirdCalDAV",
    "seedTaskRead",
    "taskWriteReadback",
    "eventCrud",
    "validation",
    "workSessionLifecycle",
    "persistentAudit",
    "spaceCreated",
    "workspaceOpened",
    "workflowUi",
    "persistentReceipt",
    "simpleUi",
    "taskFixRealUi",
    "diagnostics",
):
    assert data.get(key) is True, (key, data)
assert data["calendar"]["type"] == "caldav", data
print("real-thunderbird-restart: PASS")
PY

curl -fsS -u acceptance:test-password -X PROPFIND -H 'Depth: 1' \
  http://127.0.0.1:5232/acceptance/test/ >"$TMP/propfind-restart.xml"
python3 - "$TMP/propfind-restart.xml" <<'PY'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

root = ET.fromstring(Path(sys.argv[1]).read_bytes())
hrefs = [
    (node.text or "").strip()
    for node in root.findall(".//{DAV:}href")
    if (node.text or "").strip().endswith(".ics")
]
assert sorted(hrefs) == ["/acceptance/test/anki-recurring.ics", "/acceptance/test/seed-task.ics"], hrefs
print("radicale-clean-after-restart: PASS")
PY

echo "== Verify diagnostics survived Thunderbird restart =="
test -s "$ASSISTANT_LOG"
python3 - "$ASSISTANT_LOG" <<'PY'
from pathlib import Path
import json
import sys

lines = [line for line in Path(sys.argv[1]).read_text().splitlines() if line.strip()]
events = [json.loads(line) for line in lines]
assert sum(1 for row in events if row.get("component") == "acceptance" and row.get("event") == "probe") >= 2
assert any(row.get("component") == "background" and row.get("event") == "startup.success" for row in events)
print("persistent-diagnostics-after-restart: PASS")
PY

echo "Real Thunderbird $TB_VERSION ($TB_TIMEZONE) + real Radicale + restart + diagnostics acceptance: PASS"
