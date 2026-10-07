export class CalDAVPostPreviewChild extends JSWindowActorChild {
  async receiveMessage(message) {
    if (message.name !== "scrollToBottom") return null;
    const win = this.contentWindow;
    // Parent validated the exact Work tab and direct iframe URL before querying.
    await new Promise(resolve => win.requestAnimationFrame(() => win.requestAnimationFrame(resolve)));
    const doc = this.document;
    // Scope to this Post's body, excluding site footer, comments and navigation.
    // Classic themes use entry-content; block themes use wp-block-post-content.
    const content = doc.querySelector("article .entry-content, article .wp-block-post-content") ||
      doc.querySelector("main .entry-content, main .wp-block-post-content") ||
      doc.querySelector(".entry-content, .wp-block-post-content");
    if (!content) throw new Error("找不到文章正文，无法定位正文末尾");
    const bottom = content.getBoundingClientRect().bottom + win.scrollY;
    win.scrollTo(0, Math.max(0, bottom - win.innerHeight));
    return {url: doc.documentURI, scrollY: win.scrollY, articleBottom: bottom};
  }
}
