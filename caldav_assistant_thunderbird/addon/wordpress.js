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
      ? await AssistantWordPress.dualWriteTest()
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
    "自动每日工作日志：" +
      (config.dailyWorkLogEnabled === false ? "关闭" : "开启"),
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
  $("wp-daily-work-log").checked =
    config.dailyWorkLogEnabled !== false;
  $("wp-transport").value = config.transport || "auto";
  $("wp-url").value = config.baseUrl || "";
  $("wp-user").value = config.username || "";
  $("wp-password").value = config.applicationPassword || "";
  $("wp-allow-untrusted-tls").checked =
    Boolean(config.allowUntrustedTls);
  $("wp-path").value =
    config.wordpressPath || "/var/www/html/wordpress";
  $("wp-cli").value = config.wpCliCommand || "wp";
  await refreshStatus();
  await renderDailyTargets();
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
async function retryOutbox() {
  const result = await AssistantDailyLog.flushOutbox();
  $("outbox-receipts").textContent = JSON.stringify(result, null, 2);
  await refreshStatus();
  await renderDailyTargets();
}
async function renderDailyTargets() {
  const root = $("daily-targets"); root.replaceChildren();
  try {
    for (const {day, candidates, selectedPostId, selectionValid} of await AssistantWordPress.pendingCandidates()) {
      const staleSelection = Boolean(selectedPostId && !selectionValid);
      if (candidates.length < 2 && !staleSelection) continue;

      if (staleSelection && candidates.length < 2) {
        const warning = document.createElement("div");
        warning.textContent =
          day + "：已保存的目标 Post " + selectedPostId +
          " 已失效。" +
          (candidates.length === 1
            ? " 清除后会改用当前唯一匹配文章。"
            : " 清除后会在重试时创建新的当天文章。");
        const reset = document.createElement("button");
        reset.textContent = "清除失效目标并重试";
        reset.addEventListener("click", async () => {
          reset.disabled = true;
          try {await AssistantWordPress.clearDailyPostSelection(day); await retryOutbox();}
          catch (error) {$("outbox-receipts").textContent = String(error.message || error); reset.disabled = false;}
        });
        root.append(warning, reset);
        continue;
      }

      const label = document.createElement("label");
      label.textContent = staleSelection
        ? day + "：原目标已失效，请重新选择当天日志文章"
        : day + "：选择当天日志文章";
      const select = document.createElement("select");
      const placeholder = document.createElement("option"); placeholder.value = ""; placeholder.textContent = "请选择目标文章"; select.appendChild(placeholder);
      for (const candidate of candidates) {
        const option = document.createElement("option"); option.value = String(candidate.id); option.textContent = candidate.id + " · " + candidate.title + " · " + candidate.status; select.appendChild(option);
      }
      const button = document.createElement("button"); button.textContent = "使用所选文章并重试"; button.disabled = true;
      select.addEventListener("change", () => {button.disabled = !select.value;});
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {await AssistantWordPress.selectDailyPost(day, Number(select.value)); await retryOutbox();}
        catch (error) {$("outbox-receipts").textContent = String(error.message || error); button.disabled = false;}
      });
      label.appendChild(select); root.append(label, button);
    }
  } catch (error) {$("outbox-receipts").textContent = String(error.message || error);}
}
$("retry-outbox").addEventListener("click", async () => {
  $("retry-outbox").disabled = true;
  try {await retryOutbox();} catch (error) {$("outbox-receipts").textContent = String(error.message || error);}
  finally {$("retry-outbox").disabled = false;}
});
fetch("build-info.json").then(response => response.json()).then(info => {$("build-id").textContent = "Build " + info.buildId;}).catch(() => {});

load().catch(error => {
  $("status").textContent =
    "读取 WordPress 设置失败：" + String(error?.message || error);
});
