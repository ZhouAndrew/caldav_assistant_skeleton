export class CalDAVPostPreviewChild extends JSWindowActorChild {
  async receiveMessage(message) {
    if (message.name !== "scrollToPostEnd") return null;
    const win = this.contentWindow;
    // Wait for layout before locating the end of the single Post's content.
    await new Promise(resolve => win.requestAnimationFrame(() => win.requestAnimationFrame(resolve)));
    const doc = this.document;
    const content = doc.querySelector(
      "article .entry-content, article .wp-block-post-content, " +
      "main .wp-block-post-content, .single .entry-content, .single .wp-block-post-content"
    );
    if (!content) {
      throw new Error("WordPress Post content was not found; refusing to scroll to the site footer");
    }
    const last = content.lastElementChild || content;
    last.scrollIntoView({block: "end", inline: "nearest", behavior: "instant"});
    return {url: doc.documentURI, scrollY: win.scrollY, target: "post-content-end"};
  }
}
