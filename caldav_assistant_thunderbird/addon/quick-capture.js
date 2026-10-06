"use strict";
(() => {
  const capture = document.getElementById("quick-capture");
  const status = document.getElementById("capture-result");
  const link = document.getElementById("open-post");
  const preview = document.getElementById("post-preview");
  const previewStatus = document.getElementById("preview-status");
  let tail = Promise.resolve();

  preview.addEventListener("load", async () => {
    if (preview.hidden) return;
    const loadedUrl = preview.src;
    try {
      const doc = preview.contentDocument;
      preview.contentWindow.scrollTo(0, doc.documentElement.scrollHeight);
      previewStatus.textContent = "";
    } catch (error) {
      try {
        const tab = await browser.tabs.getCurrent();
        await browser.PostPreview.scrollToBottom(tab.id, loadedUrl);
        if (preview.src === loadedUrl) previewStatus.textContent = "";
      } catch (scrollError) {
        if (preview.src === loadedUrl) previewStatus.textContent = "预览未能加载或滚动：" + String(scrollError?.message || scrollError) + "。可打开 Post 查看。";
      }
    }
  });

  function append(content, files) {
    // Serialize only captures; never gate native Work actions on WordPress.
    tail = tail.then(async () => {
      status.textContent = "正在追加…";
      try {
        const result = await AssistantWordPress.createLog({content, files});
        status.textContent = result.success ? "✓ 已追加到今日日志" :
          (result.queued ? "已保存在 Outbox，等待重试。 " : "") + result.summary;
        if (!result.success) return;
        const post_url = result.post?.link;
        if (!post_url) { status.textContent += "（未返回 Post URL）"; return; }
        const url = new URL(post_url);
        if (!["https:", "http:"].includes(url.protocol)) throw new Error("无效的 Post URL");
        link.href = url.href;
        link.hidden = false;
        url.searchParams.set("refresh", String(Date.now()));
        preview.hidden = false;
        previewStatus.textContent = "正在加载完整 Post…";
        preview.src = url.href;
      } catch (error) {
        status.textContent = "追加失败：" + String(error?.message || error);
      }
    });
  }

  function filesFrom(data) {
    const files = [...(data?.files || [])];
    if (files.length) return files;
    return [...(data?.items || [])].filter(item => item.kind === "file")
      .map(item => item.getAsFile()).filter(Boolean);
  }
  capture.addEventListener("paste", event => {
    const files = filesFrom(event.clipboardData);
    const content = event.clipboardData?.getData("text/plain") || "";
    if (!files.length && !content.trim()) return;
    event.preventDefault();
    append(content, files);
  });
  capture.addEventListener("dragover", event => {
    if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  capture.addEventListener("drop", event => {
    const files = filesFrom(event.dataTransfer);
    if (!files.length) return;
    event.preventDefault();
    append("", files);
  });
})();
