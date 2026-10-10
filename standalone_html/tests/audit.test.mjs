import test from 'node:test';
import assert from 'node:assert/strict';
import {filterAudit,localDateKey,memoryAuditStore,readableAudit} from '../.build/audit.js';

const rows=[
  {id:'1',timestamp:'2026-10-09T01:00:00Z',localDate:'2026-10-09',scope:'connection',action:'discover',success:true,summary:'Two calendars'},
  {id:'2',timestamp:'2026-10-10T02:00:00Z',localDate:'2026-10-10',scope:'workflow',action:'task.start',success:false,summary:'Needs recovery'},
];
test('audit filters by date, scope and free text without mutation',()=>{
  assert.deepEqual(filterAudit(rows,{date:'2026-10-10',scope:'workflow',search:'RECOVERY'}).map(item=>item.id),['2']);
  assert.equal(rows.length,2);
});
test('audit text is readable and local date uses the application timezone',()=>{
  assert.match(readableAudit(rows),/connection  ✓  Two calendars/);
  assert.equal(localDateKey('2026-10-09T16:30:00Z'),'2026-10-10');
});
test('memory fallback preserves order and clears only one date',async()=>{
  const store=memoryAuditStore();await store.put(rows[1]);await store.put(rows[0]);
  assert.deepEqual((await store.list()).map(item=>item.id),['1','2']);await store.clear('2026-10-09');
  assert.deepEqual((await store.list()).map(item=>item.id),['2']);
});
