"use strict";

var { ExtensionCommon } = ChromeUtils.importESModule(
  "resource://gre/modules/ExtensionCommon.sys.mjs"
);
var { ExtensionSupport } = ChromeUtils.importESModule(
  "resource:///modules/ExtensionSupport.sys.mjs"
);
var { setTimeout, clearTimeout } = ChromeUtils.importESModule(
  "resource://gre/modules/Timer.sys.mjs"
);
const scriptLoader = Cc["@mozilla.org/moz/jssubscript-loader;1"].getService(
  Ci.mozIJSSubScriptLoader
);
const windowMediator = Cc["@mozilla.org/appshell/window-mediator;1"].getService(
  Ci.nsIWindowMediator
);
const observerService = Cc["@mozilla.org/observer-service;1"].getService(
  Ci.nsIObserverService
);
const MESSENGER_URL = "chrome://messenger/content/messenger.xhtml";

function appendTaskFixLog(event, details = {}) {
  try {
    const directoryService = Cc["@mozilla.org/file/directory_service;1"]
      .getService(Ci.nsIProperties);
    const file = directoryService.get("ProfD", Ci.nsIFile);
    file.append("caldav-assistant-experimental.log");
    if (file.exists() && file.fileSize > 1024 * 1024) {
      const backup = directoryService.get("ProfD", Ci.nsIFile);
      backup.append("caldav-assistant-experimental.log.1");
      if (backup.exists()) backup.remove(false);
      file.moveTo(null, "caldav-assistant-experimental.log.1");
    }
    const stream = Cc["@mozilla.org/network/file-output-stream;1"]
      .createInstance(Ci.nsIFileOutputStream);
    stream.init(file, 0x02 | 0x08 | 0x10, 0o600, 0);
    const converter = Cc["@mozilla.org/intl/converter-output-stream;1"]
      .createInstance(Ci.nsIConverterOutputStream);
    converter.init(stream, "UTF-8");
    converter.writeString(
      JSON.stringify({
        ts: new Date().toISOString(),
        component: "taskfix-api",
        event,
        details,
      }) + "\n"
    );
    converter.close();
  } catch (error) {
    console.warn("[TaskFix] diagnostics write failed", error);
  }
}

this.TaskFix = class extends ExtensionCommon.ExtensionAPI {
  _activated = false;
  _inject = null;
  _startupRetryTimer = null;
  _startupRetryGeneration = 0;

  _isMessengerWindow(window) {
    if (!window || window.closed) {
      return false;
    }
    const href = window.location?.href ?? "";
    const windowType =
      window.document?.documentElement?.getAttribute?.("windowtype") ?? "";
    return href.startsWith(MESSENGER_URL) || windowType === "mail:3pane";
  }

  _scheduleStartupInjection() {
    const generation = ++this._startupRetryGeneration;
    const run = attempt => {
      if (generation !== this._startupRetryGeneration || !this._inject) {
        return;
      }

      let sawMessengerWindow = false;
      for (const window of windowMediator.getEnumerator(null)) {
        if (this._isMessengerWindow(window)) {
          sawMessengerWindow = true;
          this._inject(window);
        }
      }

      // Thunderbird 153.0esr can restore the 3-pane after the Experiment API
      // has already activated.  ExtensionSupport may miss that exact load
      // transition, so keep scanning briefly.  taskfix-window.js is
      // idempotent, making repeat injection safe.
      if (attempt < 120) {
        this._startupRetryTimer = setTimeout(() => run(attempt + 1), sawMessengerWindow ? 250 : 100);
      } else {
        this._startupRetryTimer = null;
      }
    };

    if (this._startupRetryTimer !== null) {
      clearTimeout(this._startupRetryTimer);
      this._startupRetryTimer = null;
    }
    run(0);
  }

  _activate() {
    const extension = this.extension;
    const scriptURL = extension.rootURI.resolve("content/taskfix-window.js");

    if (!this._inject) {
      this._inject = window => {
        if (!this._isMessengerWindow(window)) {
          return;
        }
        try {
          scriptLoader.loadSubScript(scriptURL, window, "UTF-8");
        } catch (error) {
          appendTaskFixLog("inject-failed", {
            message: String(error?.message || error),
            href: String(window.location?.href || ""),
          });
          console.error("[TaskFix] Failed to inject task window integration", error);
        }
      };
    }

    if (!this._activated) {
      appendTaskFixLog("activate", {extensionId: String(extension.id || "")});
      ExtensionSupport.registerWindowListener(extension.id, {
        chromeURLs: [MESSENGER_URL],
        onLoadWindow: window => this._inject(window),
      });
      this._activated = true;
    }

    for (const window of windowMediator.getEnumerator(null)) {
      this._inject(window);
    }
    this._scheduleStartupInjection();
  }

  onStartup() {
    appendTaskFixLog("startup");
    try {
      this._activate();
    } catch (error) {
      appendTaskFixLog("startup-failed", {
        message: String(error?.message || error),
      });
      console.error("[TaskFix] startup activation failed", error);
    }
  }

  onShutdown(isAppShutdown) {
    appendTaskFixLog("shutdown", {isAppShutdown: Boolean(isAppShutdown)});
    this._startupRetryGeneration++;
    if (this._startupRetryTimer !== null) {
      clearTimeout(this._startupRetryTimer);
      this._startupRetryTimer = null;
    }
    if (this._activated) {
      try {
        ExtensionSupport.unregisterWindowListener(this.extension.id);
      } catch (error) {
        console.error("[TaskFix] Failed to unregister window listener", error);
      }
    }

    for (const window of windowMediator.getEnumerator(null)) {
      try {
        window.__taskfixAddonCleanup?.();
      } catch (error) {
        console.error("[TaskFix] Failed to clean up a window", error);
      }
    }

    this._activated = false;
    this._inject = null;

    if (!isAppShutdown) {
      observerService.notifyObservers(null, "startupcache-invalidate");
    }
  }

  _selectedTaskRefs() {
    const window = windowMediator.getMostRecentWindow("mail:3pane");
    if (!window || !this._isMessengerWindow(window)) return [];
    const tree = window.document.getElementById("calendar-task-tree");
    const selected = tree ? Array.from(tree.selectedTasks || []) : [];
    if (!Array.isArray(selected)) return [];
    return selected.map(task => ({
      id:String(task?.id || ""),
      calendarId:String(task?.calendar?.superCalendar?.id || task?.calendar?.id || ""),
      recurrenceId:String(task?.recurrenceId?.icalString || ""),
      title:String(task?.title || ""),
    })).filter(ref => ref.id && ref.calendarId);
  }

  getAPI() {
    return {
      TaskFix: {
        activate: () => {
          appendTaskFixLog("activate-request");
          this._activate();
        },
        getSelectedTasks: async () => this._selectedTaskRefs(),
      },
    };
  }
};
