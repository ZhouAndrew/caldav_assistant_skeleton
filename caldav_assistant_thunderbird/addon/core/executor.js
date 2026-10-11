"use strict";

// Thin effect boundary. All workflow decisions and comparisons are compiled from src/core.ts.
(() => {
  let queue = Promise.resolve();

  async function clearFinishedPointer(pointer, task, steps) {
    const plan = AssistantActionPlan.planFinishedWorkReconciliation(pointer, task);
    if (!plan) return null;
    // Workflow and reconciliation writes share this serialized effect boundary.
    if (await AssistantStorage.getCurrentWorkId() !== pointer) {
      throw new Error("Conflict: current work changed during reconciliation");
    }
    await AssistantStorage.setCurrentWorkId(plan.nextCurrentWorkId);
    const actual = await AssistantStorage.getCurrentWorkId();
    if (actual !== null) throw new Error("Validation: reconciled pointer read-back mismatch");
    steps.push({operation:"write/read-back currentWorkId",success:true,expected:null,actual});
    return plan;
  }

  async function recoverPendingMutation() {
    const pending = await AssistantStorage.getPendingTaskMutation();
    if (!pending) return null;
    const ref = pending.target;
    const actual = await browser.ThunderbirdCalDAV.getTask(ref.calendarId,ref.id,ref.recurrenceId || "",true);
    if (!AssistantActionPlan.compare(pending,actual)) throw new Error("Uncertain: previous Task write does not match authoritative read-back; no retry performed");
    const pointer = await AssistantStorage.getCurrentWorkId();
    if (pointer !== pending.beforeCurrentWorkId && pointer !== pending.nextCurrentWorkId) throw new Error("Conflict: current work changed during pending recovery");
    await AssistantStorage.setCurrentWorkId(pending.nextCurrentWorkId);
    const receipt = await AssistantStorage.persistResult({
      id:pending.id,action:pending.action,target:ref,expected:pending.expected,actual,
      success:true,verified:true,reconciled:true,outcome:"verified",
      startedAt:pending.startedAt,completedAt:new Date().toISOString(),
      summary:"此前待核实的写入已通过权威回读验证。",
      steps:[{operation:"recover task by authoritative read-back",success:true},
        {operation:"write/read-back currentWorkId",success:true,actual:pending.nextCurrentWorkId}]
    },"workflow");
    if (!receipt.logSaved && receipt.cacheSaved === false) throw new Error("Uncertain: recovery receipt could not be saved");
    await AssistantStorage.clearPendingTaskMutation(pending.id);
    if (pending.action !== "start" && globalThis.AssistantDailyLog?.queueVerifiedTaskSession) {
      try {
        const output = await AssistantDailyLog.queueVerifiedTaskSession(actual,receipt);
        if (output.queued) void AssistantDailyLog.flushOutbox().catch(()=>{});
      } catch (error) {
        await AssistantStorage.persistResult({action:"wordpress.queue-session",success:false,summary:String(error?.message || error)},"wordpress");
      }
    }
    return receipt;
  }

  async function reconcileFinishedWorkNow() {
    const recovered = await recoverPendingMutation();
    if (recovered) return recovered;
    const pointer = await AssistantStorage.getCurrentWorkId();
    if (pointer === null) return {reconciled:false};
    const ref = AssistantActionPlan.parseIdentity(pointer);
    // Only the authoritative provider read can establish a terminal Task state.
    const task = await browser.ThunderbirdCalDAV.getTask(ref.calendarId,ref.id,ref.recurrenceId || "",true);
    const plan = AssistantActionPlan.planFinishedWorkReconciliation(pointer,task);
    if (!plan) return {reconciled:false};
    const receipt = {
      id:crypto.randomUUID(),action:"reconcile-finished-work",target:plan.target,
      expected:{currentWorkId:null},actual:null,verified:false,success:false,
      startedAt:new Date().toISOString(),steps:[
        {operation:"authoritative read finished task",success:true,status:plan.observedStatus,target:plan.target}
      ]
    };
    try {
      await clearFinishedPointer(pointer,task,receipt.steps);
      receipt.actual = {currentWorkId:await AssistantStorage.getCurrentWorkId(),taskStatus:plan.observedStatus};
      receipt.verified = receipt.actual.currentWorkId === null;
      receipt.success = receipt.verified;
      receipt.reconciled = receipt.verified;
      if (!receipt.verified) throw new Error("Validation: reconciled pointer read-back mismatch");
    } catch (error) {
      receipt.error = String(error?.message || error);
      if (await AssistantStorage.getPendingTaskMutation()) receipt.outcome = "uncertain";
    }
    receipt.completedAt = new Date().toISOString();
    return AssistantStorage.persistResult(receipt,"system");
  }

  async function execute(action, reference, selectionAtClick = null) {
    const receipt = {id:crypto.randomUUID(), action, target:reference, expected:null, actual:null,
      verified:false, success:false, startedAt:new Date().toISOString(), steps:[]};
    try {
      const recovered = await recoverPendingMutation();
      if (recovered) return recovered;
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
      // Native Thunderbird may have finished this Task outside our four Actions.
      // Keep the requested action failed; only release its stale pointer.
      const finished = action === "start" ? null : AssistantActionPlan.planFinishedWorkReconciliation(currentWorkId,task);
      if (finished) {
        receipt.actual = task;
        receipt.steps.push({operation:"authoritative read finished task",success:true,status:finished.observedStatus,target:finished.target});
        await clearFinishedPointer(currentWorkId,task,receipt.steps);
        receipt.reconciled = true;
        throw new Error("Conflict: task already " + finished.observedStatus + "; currentWorkId cleared");
      }
      const plan = AssistantActionPlan.planWorkAction(action,currentWorkId,task,at,receipt.id);
      receipt.expected = plan.expected;
      if (action === "start" && !AssistantActionPlan.sameSelection(selected,await browser.TaskFix.getSelectedTasks())) {
        throw new Error("Conflict: native selection changed during task read");
      }
      await AssistantStorage.savePendingTaskMutation({id:receipt.id,action,target:plan.target,
        expected:plan.expected,beforeCurrentWorkId:currentWorkId,nextCurrentWorkId:plan.nextCurrentWorkId,
        startedAt:receipt.startedAt});
      receipt.outcome = "uncertain";
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
      receipt.outcome = "verified";
    } catch (error) {
      receipt.error = String(error?.message || error);
      if (await AssistantStorage.getPendingTaskMutation()) receipt.outcome = "uncertain";
    }
    receipt.completedAt = new Date().toISOString();
    const committed = await AssistantStorage.persistResult(receipt,"workflow");
    if (receipt.success && (committed.logSaved || committed.cacheSaved !== false)) {
      await AssistantStorage.clearPendingTaskMutation(receipt.id);
    }
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
    reconcileFinishedCurrentWork:()=>runReconciliation(),
  });
  function runReconciliation() {
    const result = queue.then(()=>reconcileFinishedWorkNow());
    queue = result.catch(()=>{});
    return result;
  }
})();
