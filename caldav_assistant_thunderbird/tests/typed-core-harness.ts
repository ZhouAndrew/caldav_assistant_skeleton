function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
function rejects(run:()=>unknown):void { let failed=false; try {run();} catch {failed=true;} assert(failed,'must reject'); }
const task: AssistantActionPlan.Task = {calendarId:'a|b',id:'uid',recurrenceId:'20261005T090000Z',status:'NEEDS-ACTION',percentComplete:35,description:'User text\n保留原文'};
const key=AssistantActionPlan.identity(task);
assert(AssistantActionPlan.parseIdentity(key)?.recurrenceId === task.recurrenceId,'identity');
assert(!AssistantActionPlan.deriveStartAvailability(null,[]),'zero');
assert(AssistantActionPlan.deriveStartAvailability(null,[task]),'one');
assert(!AssistantActionPlan.deriveStartAvailability(null,[task,task]),'many');
assert(!AssistantActionPlan.deriveStartAvailability(key,[task]),'active');
assert(!AssistantActionPlan.sameSelection([task],[{...task,id:'changed'}]),'TOCTOU');
const start=AssistantActionPlan.planWorkAction('start',null,task,'2026-10-05T00:00:00Z','unique');
const active={...task,...start.expected};
assert(AssistantActionPlan.compare(start,active),'verified');
assert(!AssistantActionPlan.compare(start,{...active,recurrenceId:'other'}),'wrong occurrence');
assert(!AssistantActionPlan.compare(start,{...active,status:'NEEDS-ACTION'}),'mismatch');
rejects(()=>AssistantActionPlan.planWorkAction('start',key,active,'2026-10-05T00:01:00Z','second'));
for(const action of ['stop','complete','cancel'] as const) {
 const plan=AssistantActionPlan.planWorkAction(action,key,active,'2026-10-05T00:02:00Z','unused');
 assert(plan.nextCurrentWorkId===null,'clear');
 assert(plan.expected.description.startsWith(task.description!),'preserve description');
 assert(AssistantActionPlan.sessions(plan.expected.description)[0]?.result===action,'close session');
 assert(plan.expected.status===(action==='stop'?'NEEDS-ACTION':action==='complete'?'COMPLETED':'CANCELLED'),'status');
 assert(plan.expected.percentComplete===(action==='complete'?100:35),'progress');
 rejects(()=>AssistantActionPlan.planWorkAction(action,null,active,'2026-10-05T00:02:00Z','unused'));
}
rejects(()=>AssistantActionPlan.sessions('x\n[CalDAV Assistant session v1] invalid'));
rejects(()=>AssistantActionPlan.planWorkAction('stop',key,task,'2026-10-05T00:02:00Z','unused'));
rejects(()=>AssistantActionPlan.planWorkAction('start',null,{...task,status:'COMPLETED'},'2026-10-05T00:02:00Z','unused'));
console.log('typed-core-harness: PASS');

const formatted={...active,description:active.description!.replace('{\"version\":1', '{ \"version\":1')};
const stoppedFormatted=AssistantActionPlan.planWorkAction('stop',key,formatted,'2026-10-05T00:02:00Z','unused');
assert(AssistantActionPlan.sessions(stoppedFormatted.expected.description)[0]?.end!==null,'close server-formatted session');
rejects(()=>AssistantActionPlan.planWorkAction('pause' as AssistantActionPlan.Action,key,active,'2026-10-05T00:02:00Z','unused'));
