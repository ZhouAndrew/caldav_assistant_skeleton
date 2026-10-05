"use strict";
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
class Node {
 constructor(id=''){this.id=id;this.children=[];this.parentNode=null;this.attrs={};this.listeners=new Map();this.disabled=false;}
 setAttribute(k,v){this.attrs[k]=String(v);}
 getAttribute(k){return this.attrs[k]??null;}
 addEventListener(k,f){this.listeners.set(k,f);}
 removeEventListener(k,f){if(this.listeners.get(k)===f)this.listeners.delete(k);}
 appendChild(n){return this.insertBefore(n,null);}
 insertBefore(n,b){n.remove();n.parentNode=this;const i=this.children.indexOf(b);this.children.splice(i<0?this.children.length:i,0,n);return n;}
 remove(){if(this.parentNode){const a=this.parentNode.children;a.splice(a.indexOf(this),1);this.parentNode=null;}}
 contains(n){return n===this || this.children.some(c=>c.contains(n));}
 get nextSibling(){return this.parentNode?.children[this.parentNode.children.indexOf(this)+1] || null;}
 click(){if(!this.disabled)this.listeners.get('command')?.();}
}
const root=new Node('root'),toolbar=new Node('task-actions-toolbar'),completed=new Node('task-actions-markcompleted'),tree=new Node('calendar-task-tree');
root.appendChild(toolbar);root.appendChild(tree);for(const id of ['category','status'])toolbar.appendChild(new Node(id));toolbar.appendChild(completed);for(const id of ['priority','delete'])toolbar.appendChild(new Node(id));
const originals=toolbar.children.slice();const nativeFunction=()=>{};
let selected=[],timers=new Map(),observer,store={},written=0;
const task={id:'a',calendar:{id:'tasks'},status:'NEEDS-ACTION',percentComplete:35,description:'Original'};
const refs=()=>selected.map(t=>({calendarId:t.calendar.id,id:t.id,recurrenceId:''}));
tree.mTreeView={};
Object.defineProperty(tree,'selectedTasks',{get:()=>selected});
const docListeners=new Map();
const doc={documentElement:root,createXULElement:()=>new Node(),getElementById(id){function find(n){return n.id===id?n:n.children.map(find).find(Boolean)}return find(root)},addEventListener:(k,f)=>docListeners.set(k,f),removeEventListener:(k,f)=>{if(docListeners.get(k)===f)docListeners.delete(k)}};
function event(){const listeners=[];return {addListener:f=>listeners.push(f),emit:(...a)=>Promise.all(listeners.map(f=>f(...a)))};}
const pointer='caldavAssistant.currentWorkId';const storageChanged=event(),onSelectionChanged=event(),onStartRequested=event();
const browser={TaskFix:{activate(){},onSelectionChanged,onStartRequested,getSelectedTasks:async()=>refs(),requestStartState:()=>scope.__caldavAssistantStartUI?.refresh(),setStartState:(_id,enabled,selection)=>scope.__caldavAssistantStartUI?.update(enabled,selection)},storage:{onChanged:storageChanged,local:{async get(keys){return Object.fromEntries((Array.isArray(keys)?keys:[keys]).map(k=>[k,structuredClone(store[k])]))},async set(values){Object.assign(store,structuredClone(values));await storageChanged.emit(Object.fromEntries(Object.keys(values).map(k=>[k,{}])));}}},runtime:{getManifest:()=>({version:'0.4.1'}),onInstalled:event(),onStartup:event(),onMessage:event()},ThunderbirdCalDAV:{writeDiagnostic:async()=>{},getTask:async(c,id,r,authoritative)=>{assert(authoritative);return {...task,id,calendarId:c,recurrenceId:r}},updateTask:async(c,id,changes)=>{written++;Object.assign(task,changes)}}};
const scope={browser,crypto:require('crypto').webcrypto,console:{log(){},warn(){},error(){}},document:doc,contextChangeTaskProgress:nativeFunction,setInterval:f=>{const id=timers.size+1;timers.set(id,f);return id},clearInterval:id=>timers.delete(id),MutationObserver:class {constructor(f){this.callback=f;observer=this;}observe(){}disconnect(){this.disconnected=true}},__caldavAssistantStartBridge:{selectionChanged:r=>onSelectionChanged.emit(1,r),start:r=>onStartRequested.emit(1,r)}};
vm.createContext(scope);
for(const file of ['core/action-plan.js','core/storage.js','core/executor.js','background.js','content/native-start.js'])vm.runInContext(fs.readFileSync('addon/'+file,'utf8'),scope,{filename:file});
const button=()=>doc.getElementById('caldav-assistant-task-start');
async function settle(){for(let i=0;i<10;i++)await new Promise(setImmediate);}
async function choose(tasks){selected=tasks;docListeners.get('select')?.();await settle();}
(async()=>{
 await settle();assert(button().disabled);assert.equal(toolbar.children.filter(n=>n.id==='caldav-assistant-task-start').length,1);assert.equal(completed.nextSibling,button());
 await choose([task]);assert(!button().disabled);
 await choose([task,{...task,id:'b'}]);assert(button().disabled);
 await choose([]);assert(button().disabled);
 await choose([task]);store[pointer]='tasks|other|';await storageChanged.emit({[pointer]:{}});await settle();assert(button().disabled);
 store[pointer]=null;await storageChanged.emit({[pointer]:{}});await settle();assert(!button().disabled);
 // Actual canonical executor rereads the native selection, never the render snapshot.
 button().click();selected=[{...task,id:'b'}];await settle();assert.equal(written,0);assert(!store['caldavAssistant.lastReceipt'].success);assert.match(store['caldavAssistant.lastReceipt'].error,/selection changed/);
 await choose([task]);button().click();await settle();assert.equal(written,1);assert(store['caldavAssistant.lastReceipt'].success);assert.equal(store[pointer],'tasks|a|');assert(button().disabled);
 // Repeated injection and toolbar reconstruction do not duplicate or alter native controls.
 for(let i=0;i<3;i++)vm.runInContext(fs.readFileSync('addon/content/native-start.js','utf8'),scope);
 assert.equal(toolbar.children.filter(n=>n.id==='caldav-assistant-task-start').length,1);
 const restored=new Node('task-actions-toolbar');toolbar.remove();root.appendChild(restored);restored.appendChild(completed);restored.appendChild(new Node('priority'));
 observer.callback();await settle();assert.equal(restored.children.filter(n=>n.id==='caldav-assistant-task-start').length,1);assert.equal(completed.nextSibling,button());
 scope.__caldavAssistantStartUI.cleanup();assert(!button());assert(observer.disconnected);assert.equal(timers.size,0);assert.equal(docListeners.size,0);assert.equal(scope.contextChangeTaskProgress,nativeFunction);
 vm.runInContext(fs.readFileSync('addon/content/native-start.js','utf8'),scope);await settle();assert(button());scope.__caldavAssistantStartUI.cleanup();assert(!button());
 // Initially absent toolbar and an uninitialized native tree are normal startup states.
 restored.remove();tree.mTreeView=null;
 vm.runInContext(fs.readFileSync('addon/content/native-start.js','utf8'),scope);await settle();assert(!button());
 const late=new Node('task-actions-toolbar');late.appendChild(completed);root.appendChild(late);
 observer.callback();await settle();assert(button().disabled);
 tree.mTreeView={};store[pointer]=null;await choose([task]);assert(!button().disabled);
 scope.__caldavAssistantStartUI.cleanup();assert(!button());assert.equal(timers.size,0);assert.equal(docListeners.size,0);
 console.log('native-start-harness: PASS (canonical core/executor, selection, TOCTOU, location, late UI, repeat injection, recreation, cleanup)');
})().catch(e=>{console.error(e);process.exitCode=1});
