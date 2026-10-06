"use strict";
(() => {
  const preview = document.getElementById("post-preview");
  const status = document.getElementById("preview-status");
  const link = document.getElementById("open-post");
  let sequence = 0;

  async function refresh() {
    const current = ++sequence;
    status.textContent = "正在读取今天的 Post…";
    try {
      const post = await AssistantWordPress.readDailyLogPost();
      if (current !== sequence) return;
      if (!post) {
        preview.hidden = true;
        link.hidden = true;
        status.textContent = "今天尚无日志 Post。";
        return;
      }
      const url = new URL(post.link);
      if (!["http:", "https:"].includes(url.protocol)) throw new Error("无效的 Post URL");
      link.href = url.href;
      link.hidden = false;
      url.searchParams.set("refresh", String(Date.now()));
      status.textContent = "正在加载完整 Post…";
      preview.hidden = false;
      preview.src = url.href;
    } catch (error) {
      if (current === sequence) status.textContent = "读取 Post 失败：" + String(error?.message || error);
    }
  }

  preview.addEventListener("load", async () => {
    if (preview.hidden) return;
    const loadedUrl = preview.src;
    try {
      try {
        preview.contentWindow.scrollTo(0, preview.contentDocument.documentElement.scrollHeight);
      } catch {
        const tab = await browser.tabs.getCurrent();
        await browser.PostPreview.scrollToBottom(tab.id, loadedUrl);
      }
      if (preview.src === loadedUrl) status.textContent = "";
    } catch (error) {
      if (preview.src === loadedUrl) status.textContent = "预览未能加载或滚动：" + String(error?.message || error) + "。可打开 Post 查看。";
    }
  });
  document.getElementById("refresh-post").addEventListener("click", refresh);
  window.addEventListener("assistant-wordpress-appended", refresh);
  refresh();
})();
