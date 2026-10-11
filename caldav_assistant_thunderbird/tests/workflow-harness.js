"use strict";
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const store={}, order=[];
let tasks=new Map(), selected=[], mismatch=false, pointerMismatch=false, duringRead=null, failWrite=false, failRead=false;
global.browser={storage:{local:{async get(k){return Object.fromEntries((Array.isArray(k)?k:[k]).map(key=>[key,structuredClone(store[key])]))},async set(v){Object.assign(store,structuredClone(v));order.push('storage-write');if(pointerMismatch && 'caldavAssistant.currentWorkId' in v)store['caldavAssistant.currentWorkId']=null;},async remove(keys){for(const k of Array.isArray(keys)?keys:[keys])delete store[k];}}},
 TaskFix:{async getSelectedTasks(){return structuredClone(selected)}},
 ThunderbirdCalDAV:{async getTask(c,id,r='',authoritative=false){order.push(authoritative?'authoritative-task-read':'task-read');if(failRead)throw new Error('offline');const t=tasks.get([c,id,r].join('|'));assert(t,'not found');if(duringRead){duringRead();duringRead=null;}const result=structuredClone(t);if(mismatch && order.includes('task-write'))result.percentComplete=73;return result;},
 async updateTask(c,id,patch,r=''){order.push('task-write');if(failWrite)throw new Error('network write rejected');Object.assign(tasks.get([c,id,r].join('|')),patch);}},};
for(const file of ['action-plan','storage','executor'])vm.runInThisContext(fs.readFileSync(`addon/core/${file}.js`,'utf8'),{filename:file});
const seed={calendarId:'tasks',id:'a',recurrenceId:'',title:'Task A',status:'NEEDS-ACTION',percentComplete:35,description:'original user description'};
function reset(){for(const k of Object.keys(store))delete store[k];order.length=0;selected=[seed];tasks=new Map([['tasks|a|',structuredClone(seed)],['tasks|b|', {...seed,id:'b'}],['tasks|rec|20261005T090000Z',{...seed,id:'rec',recurrenceId:'20261005T090000Z'}]]);mismatch=pointerMismatch=failWrite=failRead=false;duringRead=null;}
(async()=>{
 for(const count of [0,1,2]){reset();selected=count===0?[]:count===1?[seed]:[seed,{...seed,id:'b'}];const receipt=await AssistantExecutor.start(null,selected);assert.equal(receipt.success,count===1);assert.equal(order.includes('task-write'),count===1);}
 reset();let receipt=await AssistantExecutor.start(null,[seed]);assert(receipt.success && receipt.verified);assert.equal(receipt.expected.description,receipt.actual.description);assert.equal(receipt.actual.percentComplete,35);assert(order.indexOf('authoritative-task-read',order.indexOf('task-write'))<order.lastIndexOf('storage-write'));
 selected=[{...seed,id:'b'}];receipt=await AssistantExecutor.start(null,selected);assert(!receipt.success);assert.equal(tasks.get('tasks|b|').status,'NEEDS-ACTION');
 receipt=await AssistantExecutor.stop();assert(receipt.success);assert.equal(receipt.actual.status,'NEEDS-ACTION');assert.equal(receipt.actual.percentComplete,35);assert(receipt.actual.description.startsWith(seed.description));assert.equal(await AssistantStorage.getCurrentWorkId(),null);
 for(const action of ['complete','cancel']){reset();assert((await AssistantExecutor.start(null,[seed])).success);receipt=await AssistantExecutor[action]();assert(receipt.success && receipt.verified);assert.equal(receipt.actual.status,action==='complete'?'COMPLETED':'CANCELLED');assert.equal(await AssistantStorage.getCurrentWorkId(),null);}
 reset();selected=[{...seed,id:'b'}];receipt=await AssistantExecutor.start(null,[seed]);assert(!receipt.success);assert(!order.includes('task-write'));
 reset();duringRead=()=>{selected=[{...seed,id:'b'}]};receipt=await AssistantExecutor.start(null,[seed]);assert(!receipt.success);assert(!order.includes('task-write'));
 reset();mismatch=true;receipt=await AssistantExecutor.start(null,[seed]);assert(!receipt.success && !receipt.verified);assert.equal(await AssistantStorage.getCurrentWorkId(),null);
 reset();failWrite=true;receipt=await AssistantExecutor.start(null,[seed]);assert(!receipt.success);assert.equal(await AssistantStorage.getCurrentWorkId(),null);
 reset();pointerMismatch=true;receipt=await AssistantExecutor.start(null,[seed]);assert(!receipt.success);
 reset();const recurring={...seed,id:'rec',recurrenceId:'20261005T090000Z'};selected=[recurring];receipt=await AssistantExecutor.start(null,selected);assert(receipt.success);assert.equal(AssistantActionPlan.parseIdentity(await AssistantStorage.getCurrentWorkId()).recurrenceId,recurring.recurrenceId);assert((await AssistantExecutor.stop()).success);
 reset();await AssistantExecutor.start(null,[seed]); // Reload composition with storage intact (real-process restart is a separate gate).
 vm.runInThisContext(fs.readFileSync('addon/core/executor.js','utf8'));assert((await AssistantExecutor.stop()).success);
 reset(); // External Thunderbird cancellation must release only the exact stale pointer.
 assert((await AssistantExecutor.start(null,[seed])).success);
 tasks.get('tasks|a|').status='CANCELLED';order.length=0;
 let recovered=await AssistantExecutor.reconcileFinishedCurrentWork();
 assert(recovered.success && recovered.verified && recovered.reconciled);
 assert.equal(recovered.actual.taskStatus,'CANCELLED');
 assert.equal(await AssistantStorage.getCurrentWorkId(),null);
 assert(!order.includes('task-write'));
 assert(order.includes('authoritative-task-read'));
 assert.equal((await AssistantExecutor.reconcileFinishedCurrentWork()).reconciled,false);
 reset(); // External completion has the same effect.
 assert((await AssistantExecutor.start(null,[seed])).success);
 tasks.get('tasks|a|').status='COMPLETED';order.length=0;
 recovered=await AssistantExecutor.reconcileFinishedCurrentWork();
 assert(recovered.success && recovered.reconciled);
 assert.equal(await AssistantStorage.getCurrentWorkId(),null);
 assert(!order.includes('task-write'));
 reset(); // Pressing Complete on an externally cancelled Task cannot falsify its outcome.
 assert((await AssistantExecutor.start(null,[seed])).success);
 tasks.get('tasks|a|').status='CANCELLED';order.length=0;
 const terminalClick=await AssistantExecutor.complete();
 assert(!terminalClick.success && terminalClick.reconciled && /CANCELLED/.test(terminalClick.error));
 assert.equal(await AssistantStorage.getCurrentWorkId(),null);
 assert(!order.includes('task-write'));
 reset(); // Offline state: never clear an unverified pointer.
 assert((await AssistantExecutor.start(null,[seed])).success);
 tasks.get('tasks|a|').status='CANCELLED';failRead=true;
 await assert.rejects(AssistantExecutor.reconcileFinishedCurrentWork(),/offline/);
 failRead=false;
 assert.notEqual(await AssistantStorage.getCurrentWorkId(),null);
 reset(); // Pointer changed during the authoritative read: refuse to clear.
 assert((await AssistantExecutor.start(null,[seed])).success);
 tasks.get('tasks|a|').status='CANCELLED';
 duringRead=()=>{store['caldavAssistant.currentWorkId']=AssistantActionPlan.identity({...seed,id:'b'});};
 recovered=await AssistantExecutor.reconcileFinishedCurrentWork();
 assert(!recovered.success && /changed/.test(recovered.error));
 assert.equal((await AssistantStorage.getCurrentWorkId()),AssistantActionPlan.identity({...seed,id:'b'}));
 reset(); // Nonterminal pointer must never be cleared.
 assert((await AssistantExecutor.start(null,[seed])).success);
 recovered=await AssistantExecutor.reconcileFinishedCurrentWork();
 assert.equal(recovered.reconciled,false);
 assert.notEqual(await AssistantStorage.getCurrentWorkId(),null);
 reset();assert((await AssistantExecutor.start(null,[seed])).success);
 const update = browser.ThunderbirdCalDAV.updateTask;
 browser.ThunderbirdCalDAV.updateTask = async (...args)=>{await update(...args);failRead=true;};
 receipt=await AssistantExecutor.stop();
 assert(!receipt.success && receipt.outcome==='uncertain');
 assert(await AssistantStorage.getPendingTaskMutation());
 assert.notEqual(await AssistantStorage.getCurrentWorkId(),null);
 browser.ThunderbirdCalDAV.updateTask=update;failRead=false;order.length=0;
 vm.runInThisContext(fs.readFileSync('addon/core/executor.js','utf8'));
 recovered=await AssistantExecutor.reconcileFinishedCurrentWork();
 assert(recovered.success && recovered.verified);
 assert.equal(await AssistantStorage.getCurrentWorkId(),null);
 assert.equal(await AssistantStorage.getPendingTaskMutation(),null);
 assert(!order.includes('task-write'));
 reset();failWrite=true;receipt=await AssistantExecutor.start(null,[seed]);failWrite=false;order.length=0;
 receipt=await AssistantExecutor.start(null,[seed]);
 assert(!receipt.success && /Uncertain/.test(receipt.error));
 assert(!order.includes('task-write'));assert(await AssistantStorage.getPendingTaskMutation());
 // Every Action can commit while its verification response is lost.
 for (const action of ['start','complete','cancel']) {
   reset();if(action!=='start')assert((await AssistantExecutor.start(null,[seed])).success);
   browser.ThunderbirdCalDAV.updateTask=async(...args)=>{await update(...args);failRead=true;};
   receipt=await AssistantExecutor[action](null,[seed]);assert.equal(receipt.outcome,'uncertain');
   browser.ThunderbirdCalDAV.updateTask=update;failRead=false;order.length=0;
   recovered=await AssistantExecutor.reconcileFinishedCurrentWork();assert(recovered.success);
   assert.equal(await AssistantStorage.getCurrentWorkId(),action==='start'?AssistantActionPlan.identity(seed):null);
   assert(!order.includes('task-write'));
 }
 reset(); // Concurrent requests share one queue: only one Start can publish.
 const concurrent=await Promise.all([AssistantExecutor.start(null,[seed]),AssistantExecutor.start(null,[seed])]);assert.equal(concurrent.filter(r=>r.success).length,1);
 reset();global.AssistantWordPress={getConfig:()=>{throw new Error('401')}};for(const action of ['stop','complete','cancel']){reset();assert((await AssistantExecutor.start(null,[seed])).success);assert((await AssistantExecutor[action]()).success);}
 vm.runInThisContext(fs.readFileSync('addon/core/daily-log.js','utf8'));
 // Local queue errors cannot turn verified task commits into failures.
 for(const action of ['stop','complete','cancel']){reset();assert((await AssistantExecutor.start(null,[seed])).success);const done=await AssistantExecutor[action]();assert(done.success && done.verified);assert.equal((await AssistantStorage.getLastReceipt()).action,action);}
 // A permanently pending network request must not block the next work action.
 reset();global.AssistantWordPress={getConfig:async()=>({dailyWorkLogEnabled:true}),createLog:()=>new Promise(()=>{})};
 assert((await AssistantExecutor.start(null,[seed])).success);const closed=await AssistantExecutor.stop();assert(closed.success);
 assert.equal((await AssistantStorage.listWordPressOutbox()).length,1);
 await AssistantStorage.persistResult({action:'wordpress.output-failed',success:false},'wordpress');
 assert.equal((await AssistantStorage.getLastReceipt()).action,'stop');
 selected=[{...seed,id:'b'}];assert((await AssistantExecutor.start(null,selected)).success);
 assert.equal(typeof AssistantExecutor.pause,'undefined');assert.equal(typeof AssistantExecutor.resume,'undefined');
 console.log('workflow-harness: PASS (selection, TOCTOU, 4 Actions, external terminal reconciliation, read-back, concurrency, WordPress isolation)');
})().catch(e=>{console.error(e);process.exitCode=1});
