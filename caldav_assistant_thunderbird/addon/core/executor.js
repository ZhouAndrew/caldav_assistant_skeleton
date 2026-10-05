"use strict";

// Thin effect boundary. All workflow decisions and comparisons are compiled from src/core.ts.
(() => {
  let queue = Promise.resolve();
  async function execute(action, reference, selectionAtClick = null) {
    const receipt = {id:crypto.randomUUID(), action, target:reference, expected:null, actual:null,
      verified:false, success:false, startedAt:new Date().toISOString(), steps:[]};
    try {
      const selected = action === "start" ? await browser.TaskFix.getSelectedTasks() : null;
      if (action === "start" && !AssistantActionPlan.sameSelection(selectionAtClick || [], selected)) {
        throw new Error("Conflict: native selection changed");
      }
      const ref = action === "start" ? selected[0] : AssistantActionPlan.parseIdentity(await AssistantStorage.getCurrentWorkId());
      if (!ref) throw new Error("Conflict: no current work");
      receipt.target = {calendarId:ref.calendarId,id:ref.id,recurrenceId:ref.recurrenceId || ""};
      const task = await browser.ThunderbirdCalDAV.getTask(ref.calendarId,ref.id,ref.recurrenceId || "",true);
      const currentWorkId = await AssistantStorage.getCurrentWorkId();
      const at = new Date().toISOString();
      const plan = AssistantActionPlan.planWorkAction(action,currentWorkId,task,at,receipt.id);
      receipt.expected = plan.expected;
      if (action === "start" && !AssistantActionPlan.sameSelection(selected,await browser.TaskFix.getSelectedTasks())) {
        throw new Error("Conflict: native selection changed during task read");
      }
      await browser.ThunderbirdCalDAV.updateTask(ref.calendarId,ref.id,plan.expected,ref.recurrenceId || "");
      receipt.steps.push({operation:"write task",success:true,target:receipt.target,expected:plan.expected});
      const actual = await browser.ThunderbirdCalDAV.getTask(ref.calendarId,ref.id,ref.recurrenceId || "",true);
      receipt.actual = actual;
      receipt.verified = AssistantActionPlan.compare(plan,actual);
      receipt.steps.push({operation:"read-back task",success:receipt.verified,actual,expected:plan.expected});
      if (!receipt.verified) throw new Error("Validation: Task read-back mismatch");
      await AssistantStorage.setCurrentWorkId(plan.nextCurrentWorkId);
      receipt.steps.push({operation:"write/read-back currentWorkId",success:true,expected:plan.nextCurrentWorkId,actual:await AssistantStorage.getCurrentWorkId()});
      receipt.success = true;
    } catch (error) {
      receipt.error = String(error?.message || error);
    }
    receipt.completedAt = new Date().toISOString();
    const committed = await AssistantStorage.persistResult(receipt,"workflow");
    if (receipt.success && action !== "start" && globalThis.AssistantDailyLog?.queueVerifiedTaskSession) {
      try {
        const output = await AssistantDailyLog.queueVerifiedTaskSession(receipt.actual, receipt);
        if (output.queued) void AssistantDailyLog.flushOutbox().catch(() => {});
      } catch (error) {
        // The authoritative Task and currentWorkId have already committed. Output is independent.
        committed.wordpressOutput = {success:false,error:String(error?.message || error)};
        await AssistantStorage.persistResult({action:"wordpress.queue-session",success:false,summary:committed.wordpressOutput.error},"wordpress");
      }
    }
    return committed;
  }
  function run(action,reference,selectionAtClick) {
    const result = queue.then(()=>execute(action,reference,selectionAtClick));
    queue = result.catch(()=>{});
    return result;
  }
  globalThis.AssistantExecutor = Object.freeze({
    start:(reference,selection)=>run("start",reference,selection),
    stop:()=>run("stop",null,null),
    complete:()=>run("complete",null,null),
    cancel:()=>run("cancel",null,null),
  });
})();
