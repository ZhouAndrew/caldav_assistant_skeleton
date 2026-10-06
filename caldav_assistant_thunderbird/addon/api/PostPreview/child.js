export class CalDAVPostPreviewChild extends JSWindowActorChild {
  async receiveMessage(message) {
    if (message.name !== "scrollToBottom") return null;
    const win = this.contentWindow;
    // Parent validated the exact Work tab and direct iframe URL before querying.
    await new Promise(resolve => win.requestAnimationFrame(() => win.requestAnimationFrame(resolve)));
    const doc = this.document;
    win.scrollTo(0, Math.max(doc.documentElement.scrollHeight, doc.body?.scrollHeight || 0));
    return {url: doc.documentURI, scrollY: win.scrollY, height: doc.documentElement.scrollHeight};
  }
}
