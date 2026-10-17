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
      const ready = await browser.PostPreview.prepare();
      if (!ready?.success) throw new Error("滚动组件初始化失败（" + (ready?.stage || "unknown") + "）： " + (ready?.error || "unknown"));
      if (current !== sequence) return;
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
      const tab = await browser.tabs.getCurrent();
      if (!Number.isInteger(tab?.id)) throw new Error("无法定位 Thunderbird Work 标签页");
      let failure = "";
      for (let attempt = 0; attempt < 4 && !preview.hidden && preview.src === loadedUrl; attempt++) {
        const result = await browser.PostPreview.scrollToPostEnd(tab.id, loadedUrl);
        if (result?.success && result.target === "post-content-end") {
          status.textContent = "";
          return;
        }
        failure = (result?.stage || "unknown") + "： " + (result?.error || "未得到文章末尾回执");
        if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 250 * (attempt + 1)));
      }
      if (preview.src === loadedUrl) throw new Error(failure || "文章滚动未完成");
    } catch (error) {
      if (preview.src === loadedUrl) status.textContent = "预览未能滚动到文章末尾：" + String(error?.message || error) + "。可打开 Post 查看。";
    }
  });
  document.getElementById("refresh-post").addEventListener("click", refresh);
  window.addEventListener("assistant-wordpress-appended", refresh);
  refresh();
})();
