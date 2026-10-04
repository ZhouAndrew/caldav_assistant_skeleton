export type WorkflowAction = 'Start' | 'Stop' | 'Complete' | 'Cancel';
export type TaskStatus = 'NEEDS-ACTION' | 'IN-PROCESS' | 'COMPLETED' | 'CANCELLED';
export type WorkTaskId = Readonly<{ calendarId: string; uid: string; recurrenceId?: string }>;
export type Task = Readonly<{ id: WorkTaskId; description: string; status: TaskStatus; percentComplete: number }>;
export type Session = Readonly<{ id: string; startedAt: string; endedAt?: string; result?: 'Stop' | 'Complete' | 'Cancel'; previousStatus: TaskStatus; previousPercentComplete: number }>;
export type Decision = Readonly<{ task: Task; description: string; status: TaskStatus; percentComplete: number; currentWorkId: WorkTaskId | null }>;
export type DomainErrorCode = 'NotFound' | 'Conflict' | 'Validation' | 'Ambiguous' | 'Unavailable';
export class DomainError extends Error { constructor(readonly code: DomainErrorCode, message: string) { super(message); this.name = 'DomainError'; } }
export const sameWorkTaskId = (a: WorkTaskId, b: WorkTaskId): boolean => a.calendarId === b.calendarId && a.uid === b.uid && a.recurrenceId === b.recurrenceId;
export const workTaskKey = (id: WorkTaskId): string => `${id.calendarId}|${id.uid}|${id.recurrenceId ?? ''}`;
const line = /^<!-- caldav-assistant:session (\{.*\}) -->$/;
export const parseSessions = (description: string): Session[] => {
  const result: Session[] = [];
  for (const raw of description.split('\n')) { const m = line.exec(raw); if (!m) continue;
    let value: unknown; try { value = JSON.parse(m[1]); } catch { throw new DomainError('Ambiguous', 'Malformed session record'); }
    if (!value || typeof value !== 'object') throw new DomainError('Ambiguous', 'Invalid session record');
    const s = value as Partial<Session>; if (typeof s.id !== 'string' || typeof s.startedAt !== 'string' || typeof s.previousStatus !== 'string' || typeof s.previousPercentComplete !== 'number') throw new DomainError('Ambiguous', 'Incomplete session record');
    result.push(s as Session);
  }
  if (new Set(result.map(s => s.id)).size !== result.length) throw new DomainError('Ambiguous', 'Conflicting session records');
  if (result.filter(s => !s.endedAt).length > 1) throw new DomainError('Ambiguous', 'Multiple active sessions');
  return result;
};
const append = (text: string, s: Session): string => `${text}${text && !text.endsWith('\n') ? '\n' : ''}<!-- caldav-assistant:session ${JSON.stringify(s)} -->`;
const replaceSession = (text: string, id: string, replacement: string): string => text.split('\n').map(raw => { const m = line.exec(raw); if (!m) return raw; try { return (JSON.parse(m[1]) as {id?: string}).id === id ? replacement : raw; } catch { return raw; } }).join('\n');
export const decide = (action: WorkflowAction, task: Task, current: WorkTaskId | null, now: string, sessionId: string): Decision => {
  const sessions = parseSessions(task.description); const active = sessions.find(s => !s.endedAt);
  if (action === 'Start') { if (current || active) throw new DomainError('Conflict', 'A work session is already active'); const s: Session = { id: sessionId, startedAt: now, previousStatus: task.status, previousPercentComplete: task.percentComplete }; return {task, description: append(task.description, s), status: 'IN-PROCESS', percentComplete: task.percentComplete, currentWorkId: task.id}; }
  if (!current || !sameWorkTaskId(current, task.id)) throw new DomainError('Conflict', 'Task is not current work');
  if (!active) throw new DomainError('Validation', 'No active session');
  const closed: Session = {...active, endedAt: now, result: action}; const markerText = `<!-- caldav-assistant:session ${JSON.stringify(closed)} -->`; const description = replaceSession(task.description, active.id, markerText);
  if (action === 'Stop') return {task, description, status: active.previousStatus, percentComplete: active.previousPercentComplete, currentWorkId: null};
  return {task, description, status: action === 'Complete' ? 'COMPLETED' : 'CANCELLED', percentComplete: action === 'Complete' ? 100 : task.percentComplete, currentWorkId: null};
};
