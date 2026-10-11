"use strict";
const $ = id => document.getElementById(id);
let records = [];
let clearing = false;

function setLogStatus(message = "") {
  const node = $("log-status");
  node.textContent = message;
  node.hidden = !message;
}

function timeText(timestamp) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return String(timestamp || "");
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function dateKey(record) {
  return record.localDate || AssistantStorage.localDateKey(record.timestamp);
}

function filteredRecords() {
  const scope = $("scope").value;
  const selectedDate = $("date").value;
  const search = $("search").value.trim().toLowerCase();
  return records.filter(record =>
    (!scope || record.scope === scope) &&
    (!selectedDate || dateKey(record) === selectedDate) &&
    (!search || JSON.stringify(record).toLowerCase().includes(search))
  );
}

function readableStep(step) {
  const name =
    step.name ||
    [step.component, step.operation].filter(Boolean).join(" · ") ||
    "步骤";
  const state = step.success === false ? "✗" : "✓";
  const latency =
    step.latencyMs !== undefined ? " · " + step.latencyMs + " ms" : "";
  const error = step.error ? " · " + step.error : "";
  return "    " + state + " " + name + latency + error;
}

function resultText(record) {
  const details = record.details || {};
  if (details.outcome === "uncertain") return "⏳ 结果待核实";
  if (details.reconciled && !record.success) return "ℹ 已同步；请求操作未执行";
  return record.success ? "✓ 成功" : "✗ 失败";
}

function readableRecord(record) {
  const lines = [
    timeText(record.timestamp) + "  " +
      record.scope + "  " +
      resultText(record) + "  " +
      (record.summary || record.action),
  ];

  const details = record.details || {};
  lines.push("    时间：" + String(record.timestamp || ""));
  for (const key of ["id", "action", "outcome", "verified", "reconciled", "target", "expected", "actual"]) {
    if (Object.prototype.hasOwnProperty.call(details, key)) {
      lines.push("    " + key + ": " + JSON.stringify(details[key]));
    }
  }
  if (details.error) lines.push("    ✗ " + details.error);
  for (const step of details.steps || []) {
    lines.push(readableStep(step));
  }
  for (const trace of details.trace || []) {
    const state =
      trace.success === false || /error/i.test(trace.event || "") ? "✗" : "✓";
    const latency =
      trace.details?.durationMs !== undefined
        ? " · " + trace.details.durationMs + " ms"
        : "";
    const reason =
      trace.details?.reason ||
      trace.details?.error?.message ||
      trace.error ||
      "";
    lines.push(
      "    " + state + " " +
      (trace.component || "trace") + " · " +
      (trace.event || trace.operation || "event") +
      latency +
      (reason ? " · " + reason : "")
    );
  }
  return lines.join("\n");
}

function visibleText(items = filteredRecords()) {
  const groups = new Map();
  for (const record of items) {
    const day = dateKey(record) || "unknown-date";
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day).push(record);
  }

  return [...groups.keys()].sort().reverse().map(day => {
    const rows = groups.get(day)
      .slice()
      .sort((a, b) =>
        String(a.timestamp || "").localeCompare(String(b.timestamp || ""))
      )
      .map(readableRecord);
    return [day, "", ...rows].join("\n");
  }).join("\n\n");
}

async function copyText(text, successMessage) {
  if (!text) {
    setLogStatus("没有可复制的日志。");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setLogStatus(successMessage);
  } catch (error) {
    setLogStatus("复制失败：" + String(error?.message || error) + "。请重试。");
  }
}

function render() {
  const filtered = filteredRecords().slice().reverse();
  $("logs").replaceChildren();

  if (clearing) {
    $("logs").hidden = true;
    return;
  }
  $("logs").hidden = false;

  if (!records.length) {
    $("logs").textContent = "尚无操作日志。";
    return;
  }
  if (!filtered.length) {
    $("logs").textContent = "当前筛选没有匹配的日志。";
    return;
  }

  const groups = new Map();
  for (const record of filtered) {
    const day = dateKey(record) || "unknown-date";
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day).push(record);
  }

  for (const [day, dayRecords] of groups.entries()) {
    const section = document.createElement("section");
    section.className = "log-day";

    const title = document.createElement("div");
    title.className = "section-title log-day-title";
    const heading = document.createElement("h3");
    heading.textContent = day;
    const copy = document.createElement("button");
    copy.textContent = "复制这一天";
    copy.addEventListener("click", () => {
      void copyText(visibleText(dayRecords), "✓ 已复制 " + day + " 的日志。");
    });
    title.append(heading, copy);
    section.appendChild(title);

    for (const record of dayRecords) {
      const row = document.createElement("article");
      row.className = "log-record";

      const head = document.createElement("div");
      head.className = "log-head";
      const time = document.createElement("strong");
      time.textContent = timeText(record.timestamp);
      const scopeBadge = document.createElement("span");
      scopeBadge.className = "badge";
      scopeBadge.textContent = record.scope;
      const result = document.createElement("span");
      result.textContent = resultText(record);
      const copyRecord = document.createElement("button");
      copyRecord.textContent = "复制此条";
      copyRecord.addEventListener("click", () => {
        void copyText(visibleText([record]), "✓ 已复制此条日志。");
      });
      head.append(time, scopeBadge, result, copyRecord);

      const summary = document.createElement("p");
      summary.textContent = record.summary || record.action;

      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(record.details, null, 2);
      row.append(head, summary, pre);
      section.appendChild(row);
    }
    $("logs").appendChild(section);
  }
}

async function load() {
  records = await AssistantStorage.listAudit();
  render();
}

async function diagnosticsDateDefault() {
  if ($("diag-date").value) return $("diag-date").value;
  const dates =
    typeof browser.ThunderbirdCalDAV.listDiagnosticsDates === "function"
      ? await browser.ThunderbirdCalDAV.listDiagnosticsDates()
      : [];
  const date = dates?.[0] || AssistantStorage.localDateKey();
  $("diag-date").value = date;
  return date;
}

async function loadDiagnostics() {
  try {
    const date = await diagnosticsDateDefault();
    const info = await browser.ThunderbirdCalDAV.diagnosticsInfo(date);
    const data = await browser.ThunderbirdCalDAV.readDiagnostics(2000, date);
    $("diag-path").textContent = info.path
      ? "日期：" + date + " · 文件：" + info.path
      : "诊断文件不可用";
    $("diagnostics").textContent = data.text || "这一天尚无诊断日志。";
  } catch (error) {
    $("diagnostics").textContent =
      "读取技术诊断失败：" + String(error && error.message || error);
  }
}

$("scope").addEventListener("change", () => {
  setLogStatus("");
  render();
});
$("date").addEventListener("change", () => {
  setLogStatus("");
  render();
});
$("search").addEventListener("input", () => {
  setLogStatus("");
  render();
});
$("reload").addEventListener("click", async () => {
  setLogStatus("");
  await load();
});
$("copy-visible").addEventListener("click", () => {
  void copyText(visibleText(), "✓ 已复制当前可见日志。");
});
$("copy-json").addEventListener("click", () => {
  const items = filteredRecords();
  void copyText(
    items.length ? JSON.stringify(items, null, 2) : "",
    "✓ 已复制当前可见日志 JSON。"
  );
});
$("clear").addEventListener("click", () => {
  clearing = true;
  setLogStatus("");
  const date = $("date").value;
  $("clear-confirm-text").textContent = date
    ? "确认清空 " + date + " 的操作日志？"
    : "未选择日期：确认清空全部日期的操作日志？";
  $("clear-confirm").hidden = false;
  render();
});
$("clear-no").addEventListener("click", () => {
  clearing = false;
  $("clear-confirm").hidden = true;
  render();
});
$("clear-yes").addEventListener("click", async () => {
  $("clear-yes").disabled = true;
  $("clear-confirm").hidden = true;
  try {
    const date = $("date").value;
    await AssistantStorage.clearAudit(date);
    records = await AssistantStorage.listAudit();
    setLogStatus(
      date
        ? "✓ 已清空 " + date + " 的操作日志。"
        : "✓ 操作日志已清空。"
    );
  } finally {
    clearing = false;
    $("clear-yes").disabled = false;
    render();
  }
});

$("diag-date").addEventListener("change", loadDiagnostics);
$("diag-reload").addEventListener("click", loadDiagnostics);
$("diag-clear").addEventListener("click", async () => {
  const date = await diagnosticsDateDefault();
  await browser.ThunderbirdCalDAV.clearDiagnostics(date);
  await loadDiagnostics();
});
$("diag-copy").addEventListener("click", async () => {
  await copyText(
    $("diag-path").textContent + "\n" + $("diagnostics").textContent,
    "✓ 已复制当天技术诊断。"
  );
});

load();
loadDiagnostics();
