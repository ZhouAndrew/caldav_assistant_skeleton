"use strict";
const $ = id => document.getElementById(id);
let actionRunning = false;
let refreshSequence = 0;
function showNotice(message, error = false) {
  $("notice").textContent=message; $("notice").className=error?"notice error":"notice";$("notice").hidden=false;
}
async function refreshAll() {
  const sequence=++refreshSequence;
  try {
    const pointer=await AssistantStorage.getCurrentWorkId();
    const selected=await browser.TaskFix.getSelectedTasks();
    const ref=AssistantActionPlan.parseIdentity(pointer);
    const task=ref ? await browser.ThunderbirdCalDAV.getTask(ref.calendarId,ref.id,ref.recurrenceId || "") : null;
    if(sequence!==refreshSequence || actionRunning) return;
    $("no-current").hidden=pointer!==null;
    $("current-work").hidden=pointer===null;

    $("selection-status").textContent=selected.length===1 ? `已选择：${selected[0].title || selected[0].id}` : selected.length>1 ? "请只选择一个 Task。" : "请先在 Thunderbird 原生 Tasks 中选择一个 Task。";
    if(task) {
      $("current-title").textContent=task.title || "(无标题)";
      $("current-state").textContent=task.status;
      $("current-due").textContent=task.due?.icalString || "没有截止日期";
      const timing=await AssistantStorage.deriveWorkTiming(task);
      const seconds=Math.max(0,Math.floor((Date.now()-(timing.segmentStartedAtMs || Date.now()))/1000));
      $("current-elapsed").textContent=[Math.floor(seconds/3600),Math.floor(seconds/60)%60,seconds%60].map(n=>String(n).padStart(2,"0")).join(":");
    }
  } catch(error) {showNotice(String(error?.message || error),true);}
}
async function runWorkflow(action) {
  if(actionRunning) return;
  actionRunning=true; ++refreshSequence;

  $("actions").querySelectorAll("button").forEach(b=>b.disabled=true);
  try {
    const receipt=await browser.runtime.sendMessage({type:"assistant-work-action",action});
    showNotice(receipt.success?"操作已完成并回读验证。":receipt.error || "操作失败。",!receipt.success);
  } catch(error) {showNotice(String(error?.message || error),true);}
  finally {actionRunning=false;$("actions").querySelectorAll("button").forEach(b=>b.disabled=false);await refreshAll();}
}
for(const [action,label] of [["stop","停止"],["complete","完成"],["cancel","取消"]]) {
 const button=document.createElement("button");button.textContent=label;button.dataset.action=action;
 button.addEventListener("click",()=>action==="cancel" ? $("cancel-confirm").hidden=false : runWorkflow(action));$("actions").appendChild(button);
}
$("cancel-confirm-no").addEventListener("click",()=>$("cancel-confirm").hidden=true);
$("cancel-confirm-yes").addEventListener("click",()=>{$("cancel-confirm").hidden=true;runWorkflow("cancel");});
browser.ThunderbirdCalDAV.onItemsChanged.addListener(()=>{if(!actionRunning)refreshAll();});
browser.storage.onChanged.addListener(()=>{if(!actionRunning)refreshAll();});
// Read native selection directly each tick; no Task object is cached or persisted.
setInterval(()=>{if(!actionRunning)refreshAll();},500);
refreshAll();
