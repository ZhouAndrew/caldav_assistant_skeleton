"use strict";
const $ = id => document.getElementById(id);

function render(result) {
  const root = $("result");
  root.replaceChildren();
  if (!result) {
    root.textContent = "尚未写入。";
    return;
  }

  const head = document.createElement("div");
  head.className = "result-summary " + (result.success ? "ok" : "fail");
  head.textContent = result.success ? "✓ " + result.summary : (result.queued ? "日志已保存在 Outbox，等待重试。 " : "✗ ") + result.summary;
  root.appendChild(head);

  const lines = [];
  if (result.post) {
    lines.push("今日日志: " + (result.post.title || "WordPress") + " · Post ID " + result.post.id);
    if (result.post.createdToday) lines.push("今天的日志文章已自动创建");
    if (result.post.link) lines.push("URL: " + result.post.link);
  }
  for (const media of result.media || []) {
    lines.push("Media ID: " + media.id + " · " + (media.filename || "附件"));
  }
  if (result.logSaved === false) {
    lines.push("⚠ 持久日志保存失败：" + (result.logError || "未知错误"));
  } else if (result.logSaved === true) {
    lines.push("结果已写入日志");
  }

  if (lines.length) {
    const list = document.createElement("ul");
    list.className = "result-list";
    for (const line of lines) {
      const li = document.createElement("li");
      li.textContent = line;
      list.appendChild(li);
    }
    root.appendChild(list);
  }
}

$("submit").disabled = true;

AssistantWordPress.getConfig()
  .then(() => {
    $("submit").disabled = false;
  })
  .catch(error => {
    render({
      success: false,
      summary: "WordPress 设置读取失败：" + String(error?.message || error),
      media: [],
    });
  });

$("submit").addEventListener("click", async () => {
  $("submit").disabled = true;
  try {
    const result = await AssistantWordPress.createLog({
      content: $("content").value,
      files: [...$("files").files],
    });
    render(result);
    if (result.success || result.queued) {
      $("content").value = "";
      $("files").value = "";
    }
  } catch (error) {
    const message = String(error?.message || error || "Unknown error");
    const failed = await AssistantStorage.persistResult({
      action: "wordpress.append-log",
      success: false,
      startedAt: new Date().toISOString(),
      completedAt: new Date().toISOString(),
      summary: "WordPress log append failed: " + message,
      steps: [{name: "WordPress connection", success: false, error: message}],
      media: [],
    }, "wordpress");
    render(failed);
  } finally {
    $("submit").disabled = false;
  }
});

AssistantStorage.listAudit().then(records => {
  for (let i = records.length - 1; i >= 0; i--) {
    if (records[i].scope === "wordpress" && records[i].details) {
      render(records[i].details);
      break;
    }
  }
});
