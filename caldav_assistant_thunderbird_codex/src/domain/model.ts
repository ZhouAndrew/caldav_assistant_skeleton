export type WorkflowAction = 'Start' | 'Stop' | 'Complete' | 'Cancel';
export type TaskStatus = 'NEEDS-ACTION' | 'IN-PROCESS' | 'COMPLETED' | 'CANCELLED';
export type WorkTaskId = Readonly<{ calendarId: string; uid: string; recurrenceId?: string }>;
export type Task = Readonly<{ id: WorkTaskId; description: string; status: TaskStatus; percentComplete: number }>;
export type Session = Readonly<{ id: string; startedAt: string; endedAt?: string; result?: Exclude<WorkflowAction, 'Start' | 'Stop'>; previousStatus: TaskStatus; previousPercentComplete: number }>;
export type Decision = Readonly<{ task: Task; description: string; status: TaskStatus; percentComplete: number; session?: Session; currentWorkId: WorkTaskId | null }>;
export type DomainErrorCode = 'NotFound' | 'Conflict' | 'Validation' | 'Ambiguous';
export class DomainError extends Error { constructor(readonly code: DomainErrorCode, message: string) { super(message); this.name = `DomainError(${code})`; } }
export const sameWorkTaskId = (a: WorkTaskId, b: WorkTaskId): boolean => a.calendarId === b.calendarId && a.uid === b.uid && a.recurrenceId === b.recurrenceId;
const encode = (id: WorkTaskId): string => `${id.calendarId}|${id.uid}|${id.recurrenceId ?? ''}`;
const marker = /(?:^|\n)<!-- caldav-assistant:session (\{[^\n]+\}) -->/g;
export const parseSessions = (description: string): Session[] => { const out: Session[] = []; for (const match of description.matchAll(marker)) { let value: unknown; try { value = JSON.parse(match[1]); } catch { throw new DomainError('Ambiguous', 'Malformed session record'); } if (!value || typeof value !== 'object') throw new DomainError('Ambiguous', 'Invalid session record'); const s = value as Partial<Session>; if (typeof s.id !== 'string' || typeof s.startedAt !== 'string' || typeof s.previousStatus !== 'string' || typeof s.previousPercentComplete !== 'number') throw new DomainError('Ambiguous', 'Incomplete session record'); out.push(s as Session); } if (new Set(out.map(s => s.id)).size !== out.length) throw new DomainError('Ambiguous', 'Conflicting session records'); return out; };
const append = (description: string, session: Session): string => `${description}${description.endsWith('\n') || description.length === 0 ? '' : '\n'}<!-- caldav-assistant:session ${JSON.stringify(session)} -->`;
export const decide = (action: WorkflowAction, task: Task, currentWorkId: WorkTaskId | null, now: string, sessionId: string): Decision => {
  const sessions = parseSessions(task.description); const active = sessions.find(s => !s.endedAt);
  if (action === 'Start') { if (currentWorkId || active) throw new DomainError('Conflict', 'A work session is already active'); const session: Session = {id: sessionId, startedAt: now, previousStatus: task.status, previousPercentComplete: task.percentComplete}; return {task, description: append(task.description, session), status: 'IN-PROCESS', percentComplete: task.percentComplete, session, currentWorkId: task.id}; }
  if (!currentWorkId || !sameWorkTaskId(currentWorkId, task.id)) throw new DomainError('Conflict', 'Task is not current work'); if (!active) throw new DomainError('Validation', 'No active session');
  const closed = {...active, endedAt: now, result: action === 'Stop' ? undefined : action}; const description = task.description.replace(`<!-- caldav-assistant:session ${JSON.stringify(active)} -->`, `<!-- caldav-assistant:session ${JSON.stringify(closed)} -->`);
  if (action === 'Stop') return {task, description, status: active.previousStatus, percentComplete: active.previousPercentComplete, currentWorkId: null};
  return {task, description, status: action === 'Complete' ? 'COMPLETED' : 'CANCELLED', percentComplete: 100, currentWorkId: null};
};
export const workTaskKey = encode;
