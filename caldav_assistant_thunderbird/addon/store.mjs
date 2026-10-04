// Persistence adapter; pages never write this storage directly.
export function createStore(storage) {
  const get = async (key,fallback) => (await storage.get(key))[key] ?? fallback;
  const put = (key,value)=>storage.set({[key]:value});
  let tail=Promise.resolve();
  const update=(key,fallback,fn)=>{const operation=tail.then(async()=>put(key,fn(await get(key,fallback))));tail=operation.catch(()=>{});return operation;};
  return {
    pointer:()=>get('caldavAssistant.currentWorkId',null),setPointer:v=>put('caldavAssistant.currentWorkId',v),
    pending:()=>get('caldavAssistant.pendingWrite',null),savePending:v=>put('caldavAssistant.pendingWrite',v),clearPending:()=>storage.remove('caldavAssistant.pendingWrite'),
    settings:()=>get('caldavAssistant.settings',{}),saveSettings:async patch=>put('caldavAssistant.settings',{...await get('caldavAssistant.settings',{}),...patch}),
    wpConfig:async()=> (await get('caldavAssistant.settings',{})).wordpress ?? {enabled:false,mode:'auto'},
    outbox:()=>get('caldavAssistant.outbox',[]),
    enqueue:record=>update('caldavAssistant.outbox',[],all=>all.some(r=>r.id===record.id)?all:[...all,{...record,attempts:0}]),
    sent:id=>update('caldavAssistant.outbox',[],all=>all.filter(r=>r.id!==id)),
    failed:(id,error)=>update('caldavAssistant.outbox',[],all=>all.map(r=>r.id===id ? {...r,attempts:r.attempts+1,error} : r)),
    logs:async()=>[...await get('caldavAssistant.diagnosticHistory',[]),...await get('caldavAssistant.diagnostics',[])],
    diagnostic:record=>update('caldavAssistant.diagnostics',[],all=>[...all.slice(-499),record])
  };
}
