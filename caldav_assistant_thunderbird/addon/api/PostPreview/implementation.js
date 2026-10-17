"use strict";
var {ExtensionCommon} = ChromeUtils.importESModule("resource://gre/modules/ExtensionCommon.sys.mjs");
var {Services} = ChromeUtils.importESModule("resource://gre/modules/Services.sys.mjs");

this.PostPreview = class extends ExtensionCommon.ExtensionAPI {
  registered = false;
  ensureActor(context) {
    if (this.registered) return;
    const resources = Services.io.getProtocolHandler("resource").QueryInterface(Ci.nsISubstitutingProtocolHandler);
    resources.setSubstitution("caldav-assistant-post-preview", context.extension.rootURI);
    try {
      ChromeUtils.registerWindowActor("CalDAVPostPreview", {
        allFrames: true,
        child: {esModuleURI: "resource://caldav-assistant-post-preview/api/PostPreview/child.js"},
      });
      this.registered = true;
    } catch (error) {
      resources.setSubstitution("caldav-assistant-post-preview", null);
      throw error;
    }
  }
  getAPI(context) {
    const failed = (stage, error) => ({
      success: false,
      stage,
      error: String(error?.name || "Error") + ": " + String(error?.message || error),
    });
    return {PostPreview: {
      prepare: async () => {
        try {
          this.ensureActor(context);
          return {success: true};
        } catch (error) {
          return failed("register-actor", error);
        }
      },
      scrollToPostEnd: async (tabId, url) => {
        let stage = "register-actor";
        try {
          this.ensureActor(context);
          stage = "lookup-tab";
          const tab = context.extension.tabManager.get(tabId);
          const pageBrowser = tab?.nativeTab?.browser;
          if (pageBrowser?.currentURI?.spec !== context.extension.baseURI.resolve("workspace.html")) {
            throw new Error("Post preview is available only in the Work tab");
          }
          stage = "find-post-frame";
          const expected = new URL(url);
          if (!["http:", "https:"].includes(expected.protocol)) throw new Error("Invalid Post URL");
          const frame = Array.from(pageBrowser.browsingContext.children).find(child => {
            try {
              const loaded = new URL(child.currentWindowGlobal?.documentURI?.spec || "");
              return loaded.origin === expected.origin && ["http:", "https:"].includes(loaded.protocol);
            } catch (_) {return false;}
          });
          if (!frame) throw new Error("No loaded WordPress iframe on the expected origin");
          stage = "actor-scroll";
          const result = await frame.currentWindowGlobal.getActor("CalDAVPostPreview").sendQuery("scrollToPostEnd");
          if (result?.target !== "post-content-end") throw new Error("Article-end scroll was not acknowledged");
          return {success: true, ...result};
        } catch (error) {
          return failed(stage, error);
        }
      },
    }};
  }
  onShutdown() {
    if (this.registered) {
      ChromeUtils.unregisterWindowActor("CalDAVPostPreview");
      Services.io.getProtocolHandler("resource").QueryInterface(Ci.nsISubstitutingProtocolHandler)
        .setSubstitution("caldav-assistant-post-preview", null);
      this.registered = false;
    }
  }
};
