"use strict";
const root = document.getElementById("today");

function localDay(iso) {
  const d = new Date(iso);
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, "0"),
    String(d.getDate()).padStart(2, "0"),
  ].join("-");
}

function actionLabel(action) {
  return {
    start: "开始",
    stop: "结束",
    complete: "完成",
    cancel: "取消",
  }[action] || action;
}

(async () => {
  const today = localDay(new Date().toISOString());
  const records = (await AssistantStorage.listAudit()).filter(record =>
    record.scope === "workflow" &&
    localDay(record.timestamp) === today &&
    record.action !== "refresh"
  );

  if (!records.length) {
    root.textContent = "今天还没有工作记录。";
    return;
  }

  const table = document.createElement("table");
  const head = document.createElement("thead");
  head.innerHTML = "<tr><th>时间</th><th>Task</th><th>动作</th><th>结果</th></tr>";
  table.appendChild(head);

  const body = document.createElement("tbody");
  for (const record of records) {
    const tr = document.createElement("tr");
    const values = [
      new Date(record.timestamp).toLocaleTimeString(),
      record.details && record.details.task && record.details.task.title || "—",
      actionLabel(record.action),
      record.success ? "成功" : "失败",
    ];
    for (const value of values) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
  table.appendChild(body);
  root.appendChild(table);
})();
