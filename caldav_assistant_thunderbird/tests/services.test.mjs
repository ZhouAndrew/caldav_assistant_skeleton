import test from 'node:test';import assert from 'node:assert/strict';
import {createServices} from '../addon/services.mjs';import {createStore} from '../addon/store.mjs';
function fixture() {
 const data={};let mutations=0;let time='2026-10-03T09:12:05Z';
 const storage={get:async k=>structuredClone({[k]:data[k]}),set:async o=>{mutations++;Object.assign(data,structuredClone(o));},remove:async k=>{mutations++;delete data[k];}};
 const store=createStore(storage);const entries=new Map(['A','B'].map(id=>[id,{id,title:id,status:'NEEDS-ACTION',percentComplete:40,description:'原描述\n换行',revision:1}]));
 const tasks={get:async id=>structuredClone(entries.get(id)),list:async()=>structuredClone([...entries.values()]),write:async(id,patch,revision)=>{assert.equal(entries.get(id).revision,revision);entries.set(id,{...entries.get(id),...patch,revision:revision+1});}};
 let fail=true;const wp={rest:async()=>{if(fail){const e=new Error('WordPress 401');e.status=401;throw e;}return {id:7};},'wp-cli':async()=>{if(fail)throw new Error('CLI offline');return {id:8};}};
 const make=()=>createServices({tasks,store,wordpress:wp,clock:()=>time,identity:()=>crypto.randomUUID()});
 return {data,store,tasks,entries,wp,make,mutations:()=>mutations,tick:()=>time='2026-10-03T09:32:05Z',enableWP:()=>store.saveSettings({wordpress:{enabled:true,mode:'auto',restConfigured:true,wpCliConfigured:true}}),online:()=>fail=false};
}
test('realistic workflow, hidden task, concurrency, all queries read only',async()=>{
 const f=fixture(),s=f.make();await s.command('start','A');const before=f.mutations();
 await Promise.all([s.queryTask('A'),s.queryPicker({search:'B'}),s.queryLogs(),s.querySettings(),s.queryOutbox()]);assert.equal(f.mutations(),before);
 assert.deepEqual((await s.queryTask('A')).actions,['stop','complete','cancel']);assert.deepEqual((await s.queryTask('B')).actions,[]);
 await assert.rejects(s.command('start','B'),/OTHER_TASK_CURRENT/);f.tick();await s.command('stop','A');assert.equal(f.entries.get('A').percentComplete,40);
 const results=await Promise.allSettled([s.command('start','A'),s.command('start','B')]);assert.equal(results.filter(r=>r.status==='fulfilled').length,1);
});
test('WordPress failure cannot lose log or roll back task, restart and retry',async()=>{
 const f=fixture();await f.enableWP();const s=f.make();await s.command('start','A');f.tick();const result=await s.command('complete','A');assert.equal(result.committed,true);
 assert.equal(f.entries.get('A').status,'COMPLETED');assert.equal((await f.store.outbox()).length,1);
 const restarted=f.make();await restarted.recover();f.online();await restarted.retryOutbox();assert.equal((await f.store.outbox()).length,0);
});
for(const intent of ['start','stop','complete','cancel'])test(`crash after ${intent} VTODO write before pointer commit`,async()=>{
 const f=fixture(),s=f.make();await f.enableWP();if(intent!=='start'){await s.command('start','A');f.tick();}
 const set=f.store.setPointer;f.store.setPointer=async()=>{throw new Error('process crashed');};
 await assert.rejects(s.command(intent,'A'),/process crashed/);assert.ok(await f.store.pending());
 f.store.setPointer=set;await f.make().recover();assert.equal(await f.store.pointer(),intent==='start'?'A':null);assert.equal(await f.store.pending(),null);assert.equal((await f.store.outbox()).length,intent==='start'?0:1);
});
test('read-back mismatch retains pending and blocks new actions',async()=>{
 const f=fixture();f.tasks.write=async()=>{};const s=f.make();await assert.rejects(s.command('start','A'),/READ_BACK_MISMATCH/);
 await assert.rejects(s.command('start','B'),/RECOVERY_REQUIRED/);await s.recover();assert.equal(await f.store.pending(),null);
});
test('multiple open sessions never guessed',async()=>{
 const f=fixture();await f.make().command('start','A');await f.store.setPointer(null);await f.make().command('start','B');await f.store.setPointer(null);
 await assert.rejects(f.make().recover(),/MULTIPLE_CURRENT_TASKS/);assert.equal(await f.store.pointer(),null);
});
test('hanging WordPress cannot delay Complete or the next Start',{timeout:1000},async()=>{
 const f=fixture();await f.enableWP();f.wp.rest=()=>new Promise(()=>{});const s=f.make();await s.command('start','A');f.tick();
 const done=await s.command('complete','A');assert.equal(done.committed,true);assert.equal((await f.store.outbox()).length,1);
 await s.command('start','B');assert.equal(await f.store.pointer(),'B');
});
test('concurrent delivery and enqueue cannot lose Outbox records',async()=>{
 const f=fixture();await f.store.enqueue({id:'sent'});await Promise.all([f.store.sent('sent'),...Array.from({length:20},(_,i)=>f.store.enqueue({id:String(i)}))]);assert.equal((await f.store.outbox()).length,20);
});
test('hanging WordPress tools cannot lock Task commands',{timeout:1000},async()=>{
 const f=fixture();await f.enableWP();f.wp.rest=()=>new Promise(()=>{});const s=f.make();s.wordpressTest();
 await s.command('start','A');assert.equal(await f.store.pointer(),'A');
});
