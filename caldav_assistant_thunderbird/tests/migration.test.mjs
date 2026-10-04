import test from 'node:test';import assert from 'node:assert/strict';import {migrateOnce} from '../addon/migration.mjs';
import {parseWorkDescription} from '../addon/domain.mjs';
function setup(withEvidence=true) {
 const ref={calendarId:'calendar/中文',id:'uid|A',recurrenceId:''};const id=JSON.stringify([ref.calendarId,ref.id,null]);
 const values={'caldavAssistant.currentWorkId':['calendar/中文','uid|A',''].map(encodeURIComponent).join('|'),'caldavAssistant.runtime':{currentTask:ref},'caldavAssistant.wordpressOutbox':[{id:'legacy-1',payload:{title:'保留日志',content:'中文内容'}}]};
 if(withEvidence)values['caldavAssistant.audit.2026-10-03']=[{scope:'workflow',action:'start',success:true,timestamp:'2026-10-03T09:12:05Z',details:{task:{...ref,beforeStatus:'NEEDS-ACTION',beforePercentComplete:35}}}];
 let task={id,status:'IN-PROCESS',description:'原来的描述',revision:1},writes=0;
 const tasks={get:async target=>{assert.equal(target,id);return structuredClone(task);},write:async(target,patch)=>{writes++;task={...task,...patch,revision:task.revision+1};}};
 const storage={get:async key=>key===null?structuredClone(values):{[key]:values[key]},set:async patch=>Object.assign(values,patch),remove:async keys=>keys.forEach(k=>delete values[k])};
 return {values,tasks,storage,getTask:()=>task,writes:()=>writes};
}
test('once-only migration preserves user description, original baseline, pointer and Outbox',async()=>{
 const f=setup();await migrateOnce(f);assert.equal(f.values['caldavAssistant.runtime'],undefined);assert.equal(f.values['caldavAssistant.wordpressOutbox'],undefined);
 assert.equal(f.values['caldavAssistant.outbox'][0].content,'中文内容');const parsed=parseWorkDescription(f.getTask().description);assert.equal(parsed.userText,'原来的描述');assert.equal(parsed.sessions[0].before.percentComplete,35);
 await migrateOnce(f);assert.equal(f.writes(),1);
});
test('missing old baseline stops conversion and preserves all data',async()=>{const f=setup(false);await assert.rejects(migrateOnce(f),/LEGACY_START_EVIDENCE_MISSING/);assert.equal(f.writes(),0);assert.ok(f.values['caldavAssistant.runtime']);assert.ok(f.values['caldavAssistant.wordpressOutbox']);});
test('malformed description cannot be overwritten by migration',async()=>{const f=setup();const get=f.tasks.get;f.tasks.get=async id=>({...await get(id),description:'[CALDAV-ASSISTANT-WORKLOG v9]'});await assert.rejects(migrateOnce(f));assert.equal(f.writes(),0);});
