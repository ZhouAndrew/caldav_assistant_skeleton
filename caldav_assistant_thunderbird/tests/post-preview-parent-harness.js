"use strict";
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const source = fs.readFileSync("addon/api/PostPreview/implementation.js", "utf8");
assert(!source.includes("new URL("), "Native Thunderbird Experiment has no global URL constructor");
let actorRegistered = 0;
let scrolls = 0;
const registry = new Map();
const resourceHandler = {
  QueryInterface() {return this;},
  setSubstitution(name, value) {registry.set(name, value);},
};
const toNativeUri = value => {
  const url = new URL(value);
  return {spec:url.href,scheme:url.protocol.slice(0, -1),prePath:url.origin};
};
const frame = {
  currentWindowGlobal: {
    documentURI: toNativeUri("https://andrew.local/2026/10/17/post/"),
    getActor(name) {
      assert.equal(name, "CalDAVPostPreview");
      return {async sendQuery(command) {
        assert.equal(command, "scrollToPostEnd");
        scrolls++;
        return {target:"post-content-end",scrollY:1200};
      }};
    },
  },
};
const chromeBrowser = {
  currentURI:{spec:"moz-extension://test/workspace.html"},
  browsingContext:{children:[frame]},
};
const sandbox = {
  Services:{io:{newURI:toNativeUri,getProtocolHandler:()=>resourceHandler}},
  Ci:{nsISubstitutingProtocolHandler:42},
  ChromeUtils:{
    importESModule(name) {
      assert.equal(name,"resource://gre/modules/ExtensionCommon.sys.mjs");
      return {ExtensionCommon:{ExtensionAPI:class {}}};
    },
    registerWindowActor(name, options) {
      actorRegistered++;
      assert.equal(name,"CalDAVPostPreview");
      assert(options.allFrames && options.child.esModuleURI.includes("/PostPreview/child.js"));
    },
    unregisterWindowActor(name) {assert.equal(name,"CalDAVPostPreview");},
  },
};
vm.runInNewContext(source,sandbox);
const experiment = new sandbox.PostPreview();
const context = {extension:{
  rootURI:{spec:"jar:file://addon.xpi!/"},
  baseURI:{resolve:()=>chromeBrowser.currentURI.spec},
  tabManager:{get:id=>id===3?{nativeTab:{browser:chromeBrowser}}:null},
}};
(async()=>{
  const api=experiment.getAPI(context).PostPreview;
  assert.equal((await api.prepare()).success,true);
  assert.equal(actorRegistered,1,"registration must occur before iframe loads");
  const success=await api.scrollToPostEnd(3,"https://andrew.local/2026/10/17/post/?refresh=10");
  assert.equal(success.success,true);
  assert.equal(success.target,"post-content-end");
  assert.equal(scrolls,1);
  assert.equal(actorRegistered,1,"must register only once");
  const wrongOrigin=await api.scrollToPostEnd(3,"https://evil.invalid/post");
  assert.equal(wrongOrigin.success,false);
  assert.equal(wrongOrigin.stage,"find-post-frame");
  const wrongTab=await api.scrollToPostEnd(17,"https://andrew.local/post");
  assert.equal(wrongTab.success,false);
  assert.equal(wrongTab.stage,"lookup-tab");
  experiment.onShutdown();
  assert.equal(registry.get("caldav-assistant-post-preview"),null);
  console.log("post-preview-parent-harness: PASS (Gecko nsIURI, actor lifecycle, origin, frame and receipt)");
})().catch(error=>{console.error(error);process.exit(1);});
