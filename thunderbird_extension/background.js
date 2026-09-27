const HOST = "org.caldav_assistant.thunderbird";
const SPACE_NAME = "caldav_assistant";

async function ensureSpace() {
  const existing = await messenger.spaces.query({
    isSelfOwned: true,
    name: SPACE_NAME,
  });
  if (existing.length) {
    return existing[0];
  }
  return messenger.spaces.create(
    SPACE_NAME,
    {
      url: "assistant.html",
      linkHandler: "strict",
    },
    {
      title: "CalDAV Assistant",
      defaultIcons: "icon.svg",
    }
  );
}

messenger.runtime.onInstalled.addListener(() => {
  ensureSpace().catch(console.error);
});

messenger.runtime.onStartup.addListener(() => {
  ensureSpace().catch(console.error);
});

messenger.runtime.onMessage.addListener((message) => {
  if (!message || message.target !== "caldav-assistant-native") {
    return undefined;
  }
  return messenger.runtime.sendNativeMessage(HOST, message.payload);
});

ensureSpace().catch(console.error);
