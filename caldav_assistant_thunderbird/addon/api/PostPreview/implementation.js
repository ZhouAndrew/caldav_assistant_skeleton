"use strict";
var {ExtensionCommon} = ChromeUtils.importESModule("resource://gre/modules/ExtensionCommon.sys.mjs");
this.PostPreview = class extends ExtensionCommon.ExtensionAPI {
  registered = false;
  getAPI(context) {
    return {PostPreview: {scrollToPostEnd: async (tabId, url) => {
      const browser = context.extension.tabManager.get(tabId).nativeTab.browser;
      if (browser?.currentURI?.spec !== context.extension.baseURI.resolve("workspace.html")) {
        throw new Error("Post preview is available only in the Work tab");
      }
      const expected = new URL(url);
      if (!["http:", "https:"].includes(expected.protocol)) throw new Error("Invalid Post URL");
      // WordPress may canonical-redirect to its real permalink; require the iframe
      // to remain on the intended origin rather than requiring byte-equal URLs.
      const frame = browser.browsingContext.children.find(child => {
        try {
          const loaded = new URL(child.currentWindowGlobal?.documentURI?.spec || "");
          return loaded.origin === expected.origin && ["http:", "https:"].includes(loaded.protocol);
        } catch (_) {
          return false;
        }
      });
      if (!frame) throw new Error("Post preview has not loaded the expected WordPress origin");
      if (!this.registered) {
        const resources = Services.io.getProtocolHandler("resource").QueryInterface(Ci.nsISubstitutingProtocolHandler);
        resources.setSubstitution("caldav-assistant-post-preview", context.extension.rootURI);
        ChromeUtils.registerWindowActor("CalDAVPostPreview", {
          allFrames: true,
          child: {esModuleURI: "resource://caldav-assistant-post-preview/api/PostPreview/child.js"},
        });
        this.registered = true;
      }
      return frame.currentWindowGlobal.getActor("CalDAVPostPreview").sendQuery("scrollToPostEnd");
    }}};
  }
  onShutdown() {
    if (this.registered) {
      ChromeUtils.unregisterWindowActor("CalDAVPostPreview");
      Services.io.getProtocolHandler("resource").QueryInterface(Ci.nsISubstitutingProtocolHandler)
        .setSubstitution("caldav-assistant-post-preview", null);
    }
  }
};
