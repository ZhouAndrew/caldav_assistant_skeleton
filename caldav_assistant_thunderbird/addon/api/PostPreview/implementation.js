"use strict";
var {ExtensionCommon} = ChromeUtils.importESModule("resource://gre/modules/ExtensionCommon.sys.mjs");
this.PostPreview = class extends ExtensionCommon.ExtensionAPI {
  registered = false;
  getAPI(context) {
    return {PostPreview: {scrollToBottom: async (tabId, url) => {
      const browser = context.extension.tabManager.get(tabId).nativeTab.browser;
      if (browser?.currentURI?.spec !== context.extension.baseURI.resolve("workspace.html")) {
        throw new Error("Post preview is available only in the Work tab");
      }
      const frame = browser.browsingContext.children.find(child => child.currentWindowGlobal?.documentURI?.spec === url);
      if (!frame || !/^https?:\/\//.test(url)) throw new Error("Post preview has not loaded this URL");
      if (!this.registered) {
        const resources = Services.io.getProtocolHandler("resource").QueryInterface(Ci.nsISubstitutingProtocolHandler);
        resources.setSubstitution("caldav-assistant-post-preview", context.extension.rootURI);
        ChromeUtils.registerWindowActor("CalDAVPostPreview", {
          allFrames: true,
          child: {esModuleURI: "resource://caldav-assistant-post-preview/api/PostPreview/child.js"},
        });
        this.registered = true;
      }
      return frame.currentWindowGlobal.getActor("CalDAVPostPreview").sendQuery("scrollToBottom");
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
