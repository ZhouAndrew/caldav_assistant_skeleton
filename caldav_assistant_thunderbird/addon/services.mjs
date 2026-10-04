import {planTaskAction,parseWorkDescription,deriveTaskPageView,deriveTaskPickerView,deriveTodayView,wordpressTransportPolicy} from './domain.mjs';
const samePatch = (actual,patch) => Object.entries(patch).every(([k,v]) => k==='completedAt' && actual[k] && v ? Date.parse(actual[k])===Date.parse(v) : (actual[k] ?? null) === (v ?? null));
// One queue serializes commands across every extension page.
export function createServices({tasks,store,wordpress,clock,identity}) {
  let tail = Promise.resolve();
  let deliveryTail=Promise.resolve();
  const scheduleDelivery=()=>{const result=deliveryTail.then(deliver);deliveryTail=result.catch(()=>{});return result;};
  const exclusive = fn => { const result = tail.then(fn); tail = result.catch(()=>{}); return result; };
  async function queryTask(id) {
    const task = await tasks.get(id); if (!task) throw new Error('TASK_NOT_FOUND');
    return deriveTaskPageView(task,await store.pointer(),clock());
  }
  async function finalize(pending) {
    // Durable pending receipt bridges a crash between VTODO and pointer/Outbox commits.
    if (pending.log) await store.enqueue(pending.log);
    await store.setPointer(pending.pointer);
    await store.clearPending();
  }
  async function deliver() {
    const config = await store.wpConfig();
    if (!config.enabled) return;
    for (const record of await store.outbox()) {
      try { const receipt = await executeTransport(config,'createLog',record); await store.sent(record.id,receipt); }
      catch (error) { await store.failed(record.id,error.message); }
    }
  }
  async function executeTransport(config,operation,payload) {
    const policy = wordpressTransportPolicy(config);
    if (!policy.primary) throw new Error('WORDPRESS_NOT_CONFIGURED');
    try { return await wordpress[policy.primary](operation,payload,config); }
    catch (error) {
      const decision = wordpressTransportPolicy(config,error);
      if (!decision.fallback) throw error;
      await store.diagnostic({type:'wordpress-fallback',status:error.status ?? null,transport:decision.fallback});
      return wordpress[decision.fallback](operation,payload,config);
    }
  }
  return {
    queryTask,
    queryPicker:async settings => deriveTaskPickerView(settings,await tasks.list(settings)),
    queryPickerSettings:async()=>{const settings=await store.settings();return {search:settings.search ?? '',calendarId:settings.calendarId ?? ''};},
    queryToday:async ({date,timeZone})=>deriveTodayView(await tasks.list({}),date,timeZone),
    queryLogs:()=>store.logs(),queryOutbox:()=>store.outbox(),querySettings:()=>store.settings(),
    command: (intent,id) => exclusive(async()=>{
      if (await store.pending()) throw new Error('RECOVERY_REQUIRED');
      const task = await tasks.get(id); if (!task) throw new Error('TASK_NOT_FOUND');
      const plan = planTaskAction(intent,task,await store.pointer(),clock(),identity());
      const wp = await store.wpConfig();
      const pending = {taskId:id,beforeRevision:task.revision,patch:plan.taskPatch,pointer:plan.nextCurrentWorkId,log:wp.enabled && wp.autoLogEnabled!==false && plan.closedSession ? {id:plan.closedSession.id,taskId:id,title:task.title,session:plan.closedSession} : null};
      await store.savePending(pending);
      try { await tasks.write(id,plan.taskPatch,task.revision); }
      catch (error) { // Unknown write outcomes require explicit read-back recovery.
        throw new Error(`WRITE_OUTCOME_REQUIRES_RECOVERY: ${error.message}`);
      }
      const actual = await tasks.get(id);
      if (!actual || !samePatch(actual,plan.taskPatch)) {
        const fields=Object.keys(plan.taskPatch).filter(k=>!samePatch(actual ?? {},{[k]:plan.taskPatch[k]}));
        throw new Error(`READ_BACK_MISMATCH: ${fields.join(',')}`);
      }
      await finalize(pending);
      let logError = null;
      try { await store.diagnostic({type:intent,taskId:id,at:clock()}); }
      catch (error) { logError = error.message; }
      const queued=pending.log ? (await store.outbox()).find(r=>r.id===pending.log.id) : null;
      if(pending.log)scheduleDelivery().catch(error=>store.diagnostic({type:'wordpress-delivery-error',error:error.message}));
      return {committed:true,wordpress:pending.log ? queued ? 'queued' : 'sent' : 'disabled',logError:queued?.error ?? logError};
    }),
    recover:()=>exclusive(async()=>{
      const pending = await store.pending();
      if (pending) {
        const actual = await tasks.get(pending.taskId);
        if (actual && samePatch(actual,pending.patch)) await finalize(pending);
        else if(actual && actual.revision===pending.beforeRevision) await store.clearPending();
        else throw new Error('PENDING_WRITE_UNVERIFIED');
      }
      const all = await tasks.list({});
      const open = all.filter(t => parseWorkDescription(t.description ?? '').sessions.some(s=>s.end === null));
      if (open.length > 1) throw new Error('MULTIPLE_CURRENT_TASKS');
      if (open.some(t=>t.status !== 'IN-PROCESS' || t.completedAt || t.percentComplete === 100)) throw new Error('INCONSISTENT_OPEN_SESSION');
      const pointer = await store.pointer();
      if (pointer && !all.some(t=>t.id === pointer)) throw new Error('CURRENT_TASK_UNREADABLE');
      await store.setPointer(open[0]?.id ?? null);
      return {currentWorkId:open[0]?.id ?? null};
    }),
    retryOutbox:scheduleDelivery,
    wordpressTest:async()=>executeTransport(await store.wpConfig(),'test',{}),
    wordpressFullTest:async()=>executeTransport(await store.wpConfig(),'full-test',{id:identity()}),
    saveSettings:patch=>exclusive(()=>store.saveSettings(patch)),
    writeRecord:payload=>exclusive(()=>store.enqueue({...payload,id:identity()})).then(scheduleDelivery)
  };
}
