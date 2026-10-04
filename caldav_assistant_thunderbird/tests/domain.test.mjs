import test from 'node:test';
import assert from 'node:assert/strict';
import * as d from '../addon/domain.mjs';
const now='2026-10-03T17:12:05+08:00',end='2026-10-03T17:32:05+08:00';
const task={id:'calendar-A/复习',title:'英语：1 套卷子',description:'复习第三章，整理错题。\r\n链接 https://andrew.local/\n  空格保留\n🙂',status:'NEEDS-ACTION',percentComplete:35};
for(const text of ['',task.description,'尾部\n\n','[字面正文]\\n,;\t中文','a'.repeat(200000)]) test(`Description exact preservation ${text.length}`,()=>{
 const p=d.planTaskAction('start',{...task,description:text},null,now,'session-A');
 const active={...task,...p.taskPatch};const stopped=d.planTaskAction('stop',active,task.id,end);
 assert.equal(d.parseWorkDescription(stopped.taskPatch.description).userText,text);
 assert.equal(stopped.taskPatch.status,'NEEDS-ACTION');assert.equal(stopped.taskPatch.percentComplete,35);
 const parsed=d.parseWorkDescription(stopped.taskPatch.description);
 assert.deepEqual(d.parseWorkDescription(d.serializeWorkDescription(parsed)),parsed);
 assert.deepEqual(d.closeSession(parsed,'session-A',end,'stop'),parsed);
});
for(const status of [null,'NEEDS-ACTION','IN-PROCESS'])for(const percent of [null,0,35,99])test(`restore ${status}/${percent}`,()=>{
 const original={...task,status,percentComplete:percent};
 const start=d.planTaskAction('start',original,null,now,'A');
 const stop=d.planTaskAction('stop',{...original,...start.taskPatch},task.id,end);
 assert.equal(stop.taskPatch.status,status);assert.equal(stop.taskPatch.percentComplete,percent);
});
for(const intent of ['complete','cancel'])test(intent,()=>{
 const start=d.planTaskAction('start',task,null,now,'A');
 const plan=d.planTaskAction(intent,{...task,...start.taskPatch},task.id,end);
 assert.equal(plan.taskPatch.status,intent==='complete'?'COMPLETED':'CANCELLED');
 assert.equal(plan.closedSession.result,intent);assert.equal(plan.nextCurrentWorkId,null);
 if(intent==='complete'){assert.equal(plan.taskPatch.percentComplete,100);assert.equal(plan.taskPatch.completedAt,end);}
});
test('conflicting pointer blocks Start',()=>assert.throws(()=>d.planTaskAction('start',task,'another',now,'A'),/OTHER_TASK_CURRENT/));
test('unreadable current pointer does not allow Start',()=>assert.throws(()=>d.planTaskAction('start',task,'missing',now,'A'),/OTHER_TASK_CURRENT/));
test('filtered picker knows no pointer and exposes IDs only',()=>{
 const tasks=[task,{...task,id:'B',title:'化学：国庆卷第 1 套'}];
 assert.deepEqual(d.deriveTaskPickerView({search:'化学'},tasks).map(x=>x.id),['B']);
 assert.deepEqual(Object.keys(d.deriveTaskPickerView({},tasks)[0]),['id','title','status']);
});
for(const description of ['x\n\n[CALDAV-ASSISTANT-WORKLOG v1]\n{bad}\n[/CALDAV-ASSISTANT-WORKLOG]','x [CALDAV-ASSISTANT-WORKLOG v2]','[/CALDAV-ASSISTANT-WORKLOG]'])test('malformed fails closed',()=>assert.throws(()=>d.planTaskAction('start',{...task,description},null,now,'A')));
test('terminal native representations block Start',()=>{for(const change of [{status:'COMPLETED'},{status:'CANCELLED'},{percentComplete:100},{completedAt:now}])assert.deepEqual(d.deriveTaskWorkState({...task,...change},null).actions,[]);});
test('clock regression cannot close',()=>{const s=d.planTaskAction('start',task,null,end,'A');assert.throws(()=>d.planTaskAction('stop',{...task,...s.taskPatch},task.id,now),/INVALID_WORKLOG/);});
for(const status of [401,403,500])for(const mode of ['auto','rest','wp-cli'])test(`transport ${mode}/${status}`,()=>{
 const result=d.wordpressTransportPolicy({mode,restConfigured:true,wpCliConfigured:true},{status});
 assert.equal(result.primary,mode==='wp-cli'?'wp-cli':'rest');
 assert.equal(result.fallback,mode==='auto' && status!==500?'wp-cli':null);
});
