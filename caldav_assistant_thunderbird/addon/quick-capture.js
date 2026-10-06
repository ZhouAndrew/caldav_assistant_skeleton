"use strict";
(() => {
  const capture = document.getElementById("quick-capture");
  const status = document.getElementById("capture-result");
  let tail = Promise.resolve();

  function append(content, files) {
    // Serialize only captures; never gate native Work actions on WordPress.
    tail = tail.then(async () => {
      status.textContent = "正在追加…";
      try {
        const result = await AssistantWordPress.createLog({content, files});
        status.textContent = result.success ? "✓ 已追加到今日日志" :
          (result.queued ? "已保存在 Outbox，等待重试。 " : "") + result.summary;
        if (!result.success) return;
        window.dispatchEvent(new Event("assistant-wordpress-appended"));
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
