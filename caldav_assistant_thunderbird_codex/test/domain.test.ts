import test from 'node:test'; import assert from 'node:assert/strict';
import {decide, DomainError, type Task} from '../src/domain/model.js';
const task: Task = {id:{calendarId:'cal',uid:'u',recurrenceId:'2026-10-04T09:00:00Z'},description:'User text',status:'NEEDS-ACTION',percentComplete:20};
test('start and stop preserve recurring identity and prior state',()=>{const started=decide('Start',task,null,'2026-10-04T10:00:00Z','s1'); assert.equal(started.currentWorkId?.recurrenceId,task.id.recurrenceId); const stopped=decide('Stop',{...task,description:started.description,status:'IN-PROCESS'},started.currentWorkId,'2026-10-04T11:00:00Z','s2'); assert.equal(stopped.status,'NEEDS-ACTION'); assert.equal(stopped.percentComplete,20);});
test('second start is rejected',()=>assert.throws(()=>decide('Start',task,task.id,'now','s'),(e: unknown)=>e instanceof DomainError && e.code==='Conflict'));
test('malformed session is refused',()=>assert.throws(()=>decide('Start',{...task,description:'<!-- caldav-assistant:session {bad} -->'},null,'now','s'),(e: unknown)=>e instanceof DomainError && e.code==='Ambiguous'));
