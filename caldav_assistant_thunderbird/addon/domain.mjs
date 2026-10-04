// Functional core. All time, identity and facts are supplied by the caller.
const OPEN = '[CALDAV-ASSISTANT-WORKLOG v1]';
const CLOSE = '[/CALDAV-ASSISTANT-WORKLOG]';
export class DomainError extends Error { constructor(code) { super(code); this.code = code; } }
const fail = code => { throw new DomainError(code); };
const timestamp = value => typeof value === 'string' && /T.*(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
const statuses = [null, 'NEEDS-ACTION', 'IN-PROCESS', 'COMPLETED', 'CANCELLED'];
export function validateSessions(sessions) {
  if (!Array.isArray(sessions)) fail('INVALID_WORKLOG');
  const ids = new Set(); let open = 0;
  for (const s of sessions) {
    if (!s || typeof s.id !== 'string' || !s.id || ids.has(s.id) || !timestamp(s.start) ||
      !s.before || !statuses.includes(s.before.status) ||
      !(s.before.percentComplete === null || Number.isInteger(s.before.percentComplete) && s.before.percentComplete >= 0 && s.before.percentComplete <= 100)) fail('INVALID_WORKLOG');
    ids.add(s.id);
    if (s.end === null && s.result === null) open++;
    else if (!timestamp(s.end) || Date.parse(s.end) < Date.parse(s.start) || !['stop','complete','cancel'].includes(s.result)) fail('INVALID_WORKLOG');
  }
  if (open > 1 || sessions.some((s,i) => s.end === null && i !== sessions.length - 1)) fail('MULTIPLE_OPEN_SESSIONS');
  return sessions;
}
export function parseWorkDescription(text = '') {
  if (typeof text !== 'string') fail('INVALID_DESCRIPTION');
  if (!text.includes('[CALDAV-ASSISTANT-WORKLOG') && !text.includes(CLOSE)) return {userText:text,sessions:[],managed:false};
  const start = text.indexOf(OPEN);
  if (start < 2 || text.slice(start-2,start) !== '\n\n' || !text.endsWith(CLOSE) ||
      text.indexOf('[CALDAV-ASSISTANT-WORKLOG', start+1) !== -1 || text.indexOf(CLOSE) !== text.length-CLOSE.length) fail('MALFORMED_WORKLOG');
  let payload;
  try { payload = JSON.parse(text.slice(start+OPEN.length, -CLOSE.length).trim()); } catch { fail('MALFORMED_WORKLOG'); }
  if (!payload || Object.keys(payload).some(k => k !== 'sessions')) fail('UNKNOWN_WORKLOG_SCHEMA');
  return {userText:text.slice(0,start-2),sessions:validateSessions(payload.sessions),managed:true};
}
export function serializeWorkDescription(model) {
  validateSessions(model.sessions);
  return !model.managed && !model.sessions.length ? model.userText : `${model.userText}\n\n${OPEN}\n${JSON.stringify({sessions:model.sessions})}\n${CLOSE}`;
}
export function openSession(model, session) {
  if (model.sessions.some(s => s.end === null)) fail('SESSION_ALREADY_OPEN');
  const result = {...model,managed:true,sessions:[...model.sessions,structuredClone(session)]};
  validateSessions(result.sessions); return result;
}
export function closeSession(model, id, end, result) {
  const session = model.sessions.find(s => s.id === id);
  if (!session) fail('SESSION_NOT_FOUND');
  if (session.end !== null) {
    if (session.end === end && session.result === result) return model;
    fail('SESSION_ALREADY_CLOSED');
  }
  const next = {...model,sessions:model.sessions.map(s => s.id === id ? {...s,end,result} : s)};
  validateSessions(next.sessions); return next;
}
export function deriveTaskWorkState(task, pointer) {
  const model = parseWorkDescription(task.description ?? '');
  const session = model.sessions.find(s => s.end === null);
  const terminal = task.status === 'COMPLETED' || task.status === 'CANCELLED' || task.percentComplete === 100 || task.completedAt != null;
  const isCurrent = pointer === task.id;
  if ((isCurrent && !session) || (!isCurrent && session) || (session && terminal)) return {actions:[],error:'RECOVERY_REQUIRED',model,session,isCurrent};
  return {actions:isCurrent ? ['stop','complete','cancel'] : pointer || terminal ? [] : ['start'],error:!isCurrent && pointer ? 'OTHER_TASK_CURRENT' : null,model,session,isCurrent};
}
export function planTaskAction(intent, task, pointer, now, sessionId) {
  if (!timestamp(now)) fail('INVALID_TIME');
  if (task.readOnly) fail('READ_ONLY_TASK');
  const state = deriveTaskWorkState(task,pointer);
  if (!state.actions.includes(intent)) fail(state.error || 'ACTION_NOT_ALLOWED');
  let model, patch, closedSession = null;
  if (intent === 'start') {
    model = openSession(state.model,{id:sessionId,start:now,end:null,result:null,before:{status:task.status ?? null,percentComplete:task.percentComplete ?? null}});
    patch = {status:'IN-PROCESS',percentComplete:task.percentComplete ?? 0,completedAt:null};
  } else {
    model = closeSession(state.model,state.session.id,now,intent);
    closedSession = model.sessions.at(-1);
    patch = intent === 'stop' ? {...state.session.before,completedAt:null} : intent === 'complete' ? {status:'COMPLETED',percentComplete:100,completedAt:now} : {status:'CANCELLED',percentComplete:task.percentComplete,completedAt:null};
  }
  return {taskPatch:{...patch,description:serializeWorkDescription(model)},nextCurrentWorkId:intent === 'start' ? task.id : null,closedSession};
}
export function deriveTaskPickerView(settings,tasks) {
  const search = (settings.search ?? '').toLocaleLowerCase();
  return tasks.filter(t => (!settings.calendarId || t.calendarId === settings.calendarId) && t.title.toLocaleLowerCase().includes(search)).map(t=>({id:t.id,title:t.title,status:t.status}));
}
export function deriveTaskPageView(task,pointer,now) {
  const state = deriveTaskWorkState(task,pointer);
  return {id:task.id,title:task.title,status:task.status,description:state.model.userText,actions:task.readOnly ? [] : state.actions,error:task.readOnly ? 'READ_ONLY_TASK' : state.error,elapsedSeconds:state.session ? Math.max(0,Math.floor((Date.parse(now)-Date.parse(state.session.start))/1000)) : 0};
}
export function deriveTodayView(tasks,date,timeZone='Asia/Taipei') {
  const format=new Intl.DateTimeFormat('en-CA',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'});
  return tasks.flatMap(task=>parseWorkDescription(task.description ?? '').sessions.filter(session=>format.format(new Date(session.start))===date).map(session=>({taskId:task.id,title:task.title,...session})));
}
export function wordpressTransportPolicy(config,failure=null) {
  if (config.mode === 'wp-cli') return {primary:'wp-cli',fallback:null};
  if (config.mode === 'rest') return {primary:'rest',fallback:null};
  if (config.mode !== 'auto') fail('INVALID_TRANSPORT_MODE');
  if (!config.restConfigured) return {primary:config.wpCliConfigured ? 'wp-cli' : null,fallback:null};
  return {primary:'rest',fallback:config.wpCliConfigured && (!failure || failure.network || [401,403].includes(failure.status)) ? 'wp-cli' : null};
}
