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
    "assistant.html",
    { title: "CalDAV Assistant" },
  );
}

messenger.runtime.onInstalled.addListener(() => {
  ensureSpace().catch(console.error);
});

messenger.runtime.onStartup.addListener(() => {
  ensureSpace().catch(console.error);
});

ensureSpace().catch(console.error);
