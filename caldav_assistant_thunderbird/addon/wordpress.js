"use strict";
const $ = id => document.getElementById(id);
let lastResult = null;

function currentFormConfig() {
  return {
    dailyWorkLogEnabled: $("wp-daily-work-log").checked,
    transport: $("wp-transport").value,
    baseUrl: $("wp-url").value,
    username: $("wp-user").value,
    applicationPassword: $("wp-password").value,
    allowUntrustedTls: $("wp-allow-untrusted-tls").checked,
    wordpressPath: $("wp-path").value,
    wpCliCommand: $("wp-cli").value,
    legacyHelperDir: $("wp-helper-dir").value,
  };
}

async function saveConfig() {
  const config = await AssistantWordPress.saveConfig(currentFormConfig());
  const result = await AssistantStorage.persistResult({
    action: "settings.wordpress.save",
    success: true,
    startedAt: new Date().toISOString(),
    completedAt: new Date().toISOString(),
    summary: "WordPress 设置已保存。",
    steps: [{
      component: "Settings",
      operation: "save WordPress configuration",
      success: true,
      details: {
        dailyWorkLogEnabled: config.dailyWorkLogEnabled,
        transport: config.transport,
        baseUrl: config.baseUrl,
        wordpressPath: config.wordpressPath,
        wpCliCommand: config.wpCliCommand,
        allowUntrustedTls: config.allowUntrustedTls,
      },
    }],
  }, "system");

  $("save-result").textContent =
    result.logSaved === false
      ? "⚠ 设置已保存，但操作日志保存失败。"
      : "✓ WordPress 设置已保存。";
  await refreshStatus();
  return config;
}

function renderTest(result) {
  lastResult = result;
  const root = $("test-result");
  root.replaceChildren();

  const head = document.createElement("div");
  head.className = "result-summary " + (result?.success ? "ok" : "fail");
  head.textContent =
    (result?.success ? "✓ " : "✗ ") +
    (result?.summary || result?.action || "测试完成");
  root.appendChild(head);

  const logicTitle = document.createElement("h3");
  logicTitle.textContent = "测试逻辑";
  root.appendChild(logicTitle);

  const list = document.createElement("ol");
  list.className = "result-list";
  for (const step of result?.steps || []) {
    const item = document.createElement("li");
    const latency =
      step.latencyMs !== undefined ? " · " + step.latencyMs + " ms" : "";
    item.textContent =
      (step.success === false ? "✗ " : "✓ ") +
      (step.name || step.operation || "步骤") +
      latency +
      (step.error ? " · " + step.error : "");
    list.appendChild(item);
  }
  root.appendChild(list);

  const traceTitle = document.createElement("h3");
  traceTitle.textContent = "底层实际执行";
  root.appendChild(traceTitle);

  const trace = document.createElement("ol");
  trace.className = "result-list trace-list";
  for (const item of result?.trace || []) {
    const li = document.createElement("li");
    const failed =
      item.success === false || /error/i.test(item.event || "");
    const duration =
      item.details?.durationMs !== undefined
        ? " · " + item.details.durationMs + " ms"
        : "";
    const status =
      item.details?.status ? " · HTTP " + item.details.status : "";
    const reason =
      item.details?.reason ||
      item.details?.error?.message ||
      item.error ||
      "";
    li.textContent =
      (failed ? "✗ " : "✓ ") +
      (item.timestamp || "") + " · " +
      (item.component || "trace") + " · " +
      (item.event || item.operation || "event") +
      duration + status +
      (reason ? " · " + reason : "");
    trace.appendChild(li);
  }
  if (!(result?.trace || []).length) {
    const li = document.createElement("li");
    li.textContent = "没有可读取的底层诊断步骤。";
    trace.appendChild(li);
  }
  root.appendChild(trace);

  const jsonTitle = document.createElement("h3");
  jsonTitle.textContent = "完整结果 JSON";
  root.appendChild(jsonTitle);
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(result, null, 2);
  root.appendChild(pre);
}

async function runTest(kind) {
  await saveConfig();
  const result =
    kind === "full"
      ? await AssistantWordPress.fullWriteTest()
      : await AssistantWordPress.quickTest();
  renderTest(result);
  await refreshStatus();
}

async function refreshStatus() {
  const config = await AssistantWordPress.getConfig();
  const audit = await AssistantStorage.listAudit();
  const lastWrite = audit.slice().reverse().find(record =>
    record.scope === "wordpress" &&
    record.action === "wordpress.append-log" &&
    record.success
  );
  const outbox = await AssistantStorage.listWordPressOutbox();

  $("status").textContent = [
    "配置 Transport：" + config.transport,
    "WordPress URL：" + (config.baseUrl || "(未设置)"),
    "WordPress 本地路径：" + (config.wordpressPath || "(未设置)"),
    "WP-CLI：" + (config.wpCliCommand || "(未设置)"),
    "TLS 本地忽略校验：" +
      (config.allowUntrustedTls ? "开启" : "关闭"),
    "最后一次实际日志写入：" +
      (lastWrite
        ? new Date(lastWrite.timestamp).toLocaleString() +
          " · " + (lastWrite.summary || "")
        : "尚无"),
    "待补写 Outbox：" + outbox.length,
  ].join("\n");

  $("outbox-status").textContent =
    outbox.length
      ? "有 " + outbox.length + " 条 WordPress 日志等待补写。"
      : "Outbox 为空。";
}

async function load() {
  const config = await AssistantWordPress.getConfig();
  $("wp-transport").value = config.transport || "auto";
  $("wp-url").value = config.baseUrl || "";
  $("wp-user").value = config.username || "";
  $("wp-password").value = config.applicationPassword || "";
  $("wp-allow-untrusted-tls").checked =
    Boolean(config.allowUntrustedTls);
  $("wp-path").value =
    config.wordpressPath || "/var/www/html/wordpress";
  $("wp-cli").value = config.wpCliCommand || "wp";
  $("wp-helper-dir").value = config.legacyHelperDir || "~/bin";
  await refreshStatus();
}

$("save").addEventListener("click", () => void saveConfig());
$("quick").addEventListener("click", () => void runTest("quick"));
$("full").addEventListener("click", () => void runTest("full"));
$("copy-result").addEventListener("click", async () => {
  await navigator.clipboard.writeText(
    lastResult
      ? JSON.stringify(lastResult, null, 2)
      : "尚未测试。"
  );
});
$("copy-config").addEventListener("click", async () => {
  const config = currentFormConfig();
  const safe = {
    ...config,
    applicationPassword:
      config.applicationPassword ? "[configured]" : "",
  };
  await navigator.clipboard.writeText(JSON.stringify(safe, null, 2));
});
$("retry-outbox").addEventListener("click", async () => {
  const result = await AssistantWordPressOutbox.flushOutbox();
  $("outbox-status").textContent =
    "Outbox 重试完成：处理 " + (result.processed || 0) +
    "，成功 " + (result.sent || 0) +
    "，失败 " + (result.failed || 0) + "。";
  await refreshStatus();
});

load().catch(error => {
  $("status").textContent =
    "读取 WordPress 设置失败：" + String(error?.message || error);
});
