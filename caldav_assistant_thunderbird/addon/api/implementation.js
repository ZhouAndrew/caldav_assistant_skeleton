var {ExtensionCommon} = ChromeUtils.importESModule('resource://gre/modules/ExtensionCommon.sys.mjs');
var {ExtensionUtils} = ChromeUtils.importESModule('resource://gre/modules/ExtensionUtils.sys.mjs');
var assistantNative = class extends ExtensionCommon.ExtensionAPI {
  getAPI(context) {
    const alias = `caldav-assistant-${context.extension.uuid}`;
    const resources = Services.io.getProtocolHandler('resource').QueryInterface(Ci.nsIResProtocolHandler);
    resources.setSubstitution(alias,context.extension.rootURI);
    const url = `resource://${alias}/native-calendar.mjs`;
    const {nativeTasks} = ChromeUtils.importESModule(url);
    const {wpCli} = ChromeUtils.importESModule(`resource://${alias}/native-wordpress.mjs`);
    context.callOnClose({close(){resources.setSubstitution(alias,null);}});
    const expose = fn => async(...args)=>{try{return await fn(...args);}catch(error){console.error('CalDAV Assistant native:',error);throw new ExtensionUtils.ExtensionError(error.message);}};
    return {assistantNative:{get:expose(nativeTasks.get),list:expose(nativeTasks.list),write:expose(nativeTasks.write),wpCli:expose(wpCli)}};
  }
};
