import test from 'node:test';import assert from 'node:assert/strict';import * as views from '../addon/views.mjs';
test('Task page only renders actions supplied by domain',()=>{
 const model={id:'A',title:'中文 <script>',status:'IN-PROCESS',description:'用户文字',elapsedSeconds:1,actions:['stop','complete','cancel'],error:null};
 const original=structuredClone(model);const result=views.taskPage(model);assert.deepEqual(model,original);assert.deepEqual(result.filter(r=>r.tag==='button').map(r=>r.attrs['data-action']),model.actions);assert.equal(result[0].text,'中文 <script>');
});
test('Picker is a selector and never returns workflow controls',()=>{
 const result=views.pickerPage({search:''},[{id:'A/中文',title:'Task'}]);const serialized=JSON.stringify(result);assert.ok(serialized.includes('page.html?id='));assert.ok(!serialized.includes('data-action'));
});
test('Logs and Today views contain no commands',()=>{for(const view of [views.logsPage([{type:'complete'}]),views.todayPage('2026-10-03',[{title:'Task',start:'2026-10-03T09:00:00Z',end:null}])])assert.ok(!JSON.stringify(view).includes('data-action'));});
