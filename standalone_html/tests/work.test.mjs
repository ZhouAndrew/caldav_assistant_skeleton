import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createWork,planResource} from '../.build/work.js';
import {projectTasks} from '../.build/tasks.js';
const calendar='https://test/calendar/';
const initial={url:calendar+'task.ics',etag:'"1"',text:'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:one\r\nSUMMARY:Original\r\nDESCRIPTION:User notes\r\nSTATUS:NEEDS-ACTION\r\nDUE;VALUE=DATE:20261008\r\nX-USER-DATA:keep\r\nEND:VTODO\r\nEND:VCALENDAR\r\n'};
const selected=projectTasks(calendar,initial)[0];
test('canonical core drives start, stop, complete and cancel; pointer follows verified receipt',async()=>{
 for(const finish of ['stop','complete','cancel']) {
  let resource=initial, pointer=null;
  const transport={read:async()=>resource,writeVerified:async(url,text,etag,compare)=>{
   assert.equal(etag,resource.etag);
   assert.ok(compare(text,text));
   resource={url,text,etag:'"new"'};
   return {verified:true,resource};
  }};
  const work=createWork(transport,{read:()=>pointer,publish:value=>{pointer=value;}});
  await work.run('start',selected,'2026-10-07T00:00:00Z','token');
  assert.ok(pointer);assert.match(resource.text,/X-USER-DATA:keep/);assert.match(resource.text,/DUE;VALUE=DATE:20261008/);
  await work.run(finish,selected,'2026-10-07T00:01:00Z','unused');
  assert.equal(pointer,null);
  assert.equal(projectTasks(calendar,resource)[0].status,{stop:'NEEDS-ACTION',complete:'COMPLETED',cancel:'CANCELLED'}[finish]);
  assert.match(resource.text,/User notes/);
 }
});
test('conflict and failed validation never publish currentWorkId',async()=>{
 let published=0;
 for(const code of ['Conflict','Validation']) {
  const work=createWork({read:async()=>initial,writeVerified:async()=>{throw {code};}}, {read:()=>null,publish:()=>published++});
  await assert.rejects(work.run('start',selected,'2026-10-07T00:00:00Z','token'),{code});
 }
 assert.equal(published,0);
});
test('recurring series refuses mutation',()=>{
 const resource={...initial,text:initial.text.replace('UID:one','UID:one\r\nRRULE:FREQ=DAILY')};
 assert.throws(()=>planResource('start',null,projectTasks(calendar,resource)[0],resource,'2026-10-07T00:00:00Z','token'),{code:'Validation'});
});
test('read-back validation rejects lost user data and altered workflow fields',async()=>{
 let published=false;
 const work=createWork({read:async()=>initial,writeVerified:async(_url,text,_etag,compare)=>{
  assert.equal(compare(text,text.replace('X-USER-DATA:keep','X-USER-DATA:lost')),false);
  assert.equal(compare(text,text.replace('STATUS:IN-PROCESS','STATUS:NEEDS-ACTION')),false);
  throw {code:'Validation'};
 }},{read:()=>null,publish:()=>{published=true;}});
 await assert.rejects(work.run('start',selected,'2026-10-07T00:00:00Z','token'),{code:'Validation'});
 assert.equal(published,false);
});
