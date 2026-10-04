// Isolated, one-time conversion of persisted 0.3.16 data. No old module imports.
import {parseWorkDescription,openSession,serializeWorkDescription} from './domain.mjs';
const MARKER='caldavAssistant.descriptionMigrationV1';
function convertId(value) {
  if(!value)return null;
  try{const id=JSON.parse(value);if(Array.isArray(id)&&id.length===3)return value;}catch{}
  const parts=String(value).split('|');
  if(parts.length!==3)throw new Error('LEGACY_TASK_ID_INVALID');
  const [calendar,uid,rid]=parts.map(decodeURIComponent);
  return JSON.stringify([calendar,uid,rid||null]);
}
function refId(task){return task ? JSON.stringify([task.calendarId,task.id,task.recurrenceId||null]) : null;}
export async function migrateOnce({storage,tasks}) {
  if((await storage.get(MARKER))[MARKER])return;
  const values=await storage.get(null);
  const auditKeys=Object.keys(values).filter(key=>key==='caldavAssistant.audit'||key.startsWith('caldavAssistant.audit.'));
  const records=auditKeys.flatMap(key=>Array.isArray(values[key])?values[key]:[]);
  const legacy=values['caldavAssistant.runtime'];
  const pointer=convertId(values['caldavAssistant.currentWorkId']) ?? refId(legacy?.currentTask);
  if(pointer) {
    const task=await tasks.get(pointer),parsed=parseWorkDescription(task.description);
    if(!parsed.sessions.some(s=>s.end===null)) {
      if(task.status!=='IN-PROCESS')throw new Error('LEGACY_CURRENT_TASK_REQUIRES_REVIEW');
      const starts=records.filter(r=>r.scope==='workflow' && r.action==='start' && r.success!==false && r.details?.success!==false && refId(r.details?.task)===pointer);
      starts.sort((a,b)=>Date.parse(b.timestamp)-Date.parse(a.timestamp));
      const latest=starts[0];
      const before=latest ? {status:latest.details.task.beforeStatus,percentComplete:latest.details.task.beforePercentComplete} : legacy?.taskBeforeStart;
      const start=latest?.timestamp ?? (legacy?.segmentStartedAtMs ? new Date(legacy.segmentStartedAtMs).toISOString() : null);
      // Missing evidence is an explicit migration error, never an invented baseline.
      if(!before || !start || !('status' in before) || !('percentComplete' in before))throw new Error('LEGACY_START_EVIDENCE_MISSING');
      const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(pointer+'\n'+start));
      const sessionId='migration-v1-'+Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
      const model=openSession(parsed,{id:sessionId,start,end:null,result:null,before:{status:before.status,percentComplete:Number(before.percentComplete)}});
      const description=serializeWorkDescription(model);await tasks.write(pointer,{description},task.revision);
      if((await tasks.get(pointer)).description!==description)throw new Error('MIGRATION_READBACK_MISMATCH');
    }
  }
  const oldOutbox=values['caldavAssistant.wordpressOutbox'];
  if(oldOutbox && !Array.isArray(oldOutbox))throw new Error('LEGACY_OUTBOX_INVALID');
  const outbox=[...(values['caldavAssistant.outbox'] ?? [])];
  for(const old of oldOutbox ?? [])if(!outbox.some(record=>record.id===old.id)) {
    const payload=old.payload ?? old;
    outbox.push({id:old.id,title:payload.title ?? '历史待发送记录',content:typeof payload.content==='string'?payload.content:JSON.stringify(payload),attempts:old.attempts ?? 0,error:old.lastError ?? null});
  }
  const settings=values['caldavAssistant.settings'] ?? {};
  const oldWP=settings.wordpress;
  let wordpress=oldWP;
  if(oldWP && !oldWP.mode) {
    wordpress={...oldWP,mode:oldWP.transport==='application-password'?'rest':oldWP.transport ?? 'auto',url:oldWP.baseUrl,password:oldWP.applicationPassword,wpPath:oldWP.wordpressPath,wpExecutable:oldWP.wpCliExecutable,restConfigured:Boolean(oldWP.baseUrl && oldWP.username && oldWP.applicationPassword),wpCliConfigured:Boolean(oldWP.wordpressPath),autoLogEnabled:oldWP.dailyWorkLogEnabled!==false};
  }
  const history=[...new Map([...(values['caldavAssistant.diagnosticHistory'] ?? []),...records].map(record=>[JSON.stringify(record),record])).values()];
  await storage.set({'caldavAssistant.currentWorkId':pointer,'caldavAssistant.outbox':outbox,'caldavAssistant.settings':wordpress?{...settings,wordpress}:settings,'caldavAssistant.diagnosticHistory':history});
  await storage.remove(['caldavAssistant.runtime','caldavAssistant.wordpressOutbox',...auditKeys,'caldavAssistant.auditDates']);
  await storage.set({[MARKER]:true});
}
