/** Canonical business source. Packaging compiles this file; never edit generated JS. */
namespace AssistantActionPlan {
  export type Action = 'start' | 'stop' | 'complete' | 'cancel';
  export interface Identity { readonly calendarId: string; readonly id: string; readonly recurrenceId?: string; }
  export interface Task extends Identity { readonly status: string; readonly percentComplete: number; readonly description?: string; }
  export interface Session { readonly version: 1; readonly identity: string; readonly token: string; readonly start: string; readonly beforeStatus: string; readonly beforePercent: number; readonly end: string | null; readonly result: Action | null; }
  export interface Changes { readonly status: string; readonly percentComplete: number; readonly description: string; }
  export interface Plan { readonly action: Action; readonly target: Identity; readonly expected: Changes; readonly nextCurrentWorkId: string | null; }
  const marker = '\n[CalDAV Assistant session v1] ';
  export function identity(ref: Identity): string {
    if (!ref.calendarId || !ref.id) throw new Error('Validation: missing identity');
    return [ref.calendarId, ref.id, ref.recurrenceId || ''].map(encodeURIComponent).join('|');
  }
  export function parseIdentity(value: string | null): Identity | null {
    if (value === null) return null;
    const parts = value.split('|');
    if (parts.length !== 3) throw new Error('Validation: malformed currentWorkId');
    const [calendarId, id, recurrenceId] = parts.map(decodeURIComponent);
    if (!calendarId || !id) throw new Error('Validation: empty currentWorkId');
    return Object.freeze({calendarId, id, recurrenceId: recurrenceId || ''});
  }
  export function deriveStartAvailability(currentWorkId: string | null, selection: readonly Identity[]): boolean {
    return currentWorkId === null && selection.length === 1;
  }
  export function sameSelection(a: readonly Identity[], b: readonly Identity[]): boolean {
    return a.length === 1 && b.length === 1 && identity(a[0]!) === identity(b[0]!);
  }
  export function sessions(description: string): readonly Session[] {
    const records: Session[] = [];
    for (const raw of description.split(marker).slice(1)) {
      const line = raw.split('\n')[0] || '';
      let value: unknown;
      try { value = JSON.parse(line); } catch { throw new Error('Validation: malformed session'); }
      if (typeof value !== 'object' || value === null) throw new Error('Validation: invalid session');
      const s = value as Record<string, unknown>;
      if (s.version !== 1 || typeof s.identity !== 'string' || typeof s.token !== 'string' || !s.token ||
          typeof s.start !== 'string' || !Number.isFinite(Date.parse(s.start)) ||
          !['', 'NEEDS-ACTION', 'IN-PROCESS'].includes(String(s.beforeStatus)) ||
          typeof s.beforePercent !== 'number' || !Number.isInteger(s.beforePercent) || s.beforePercent < 0 || s.beforePercent > 99 ||
          !(s.end === null || (typeof s.end === 'string' && Number.isFinite(Date.parse(s.end)))) ||
          !(s.result === null || ['stop','complete','cancel'].includes(String(s.result))) ||
          (s.end === null) !== (s.result === null)) throw new Error('Validation: invalid session');
      records.push(Object.freeze(value as Session));
    }
    if (new Set(records.map(s => s.token)).size !== records.length || records.filter(s => s.end === null).length > 1) {
      throw new Error('Ambiguous: duplicate or multiple open sessions');
    }
    return Object.freeze(records);
  }
  export function planWorkAction(action: Action, currentWorkId: string | null, task: Task, at: string, token: string): Plan {
    if (!['start','stop','complete','cancel'].includes(action)) throw new Error('Validation: unsupported action');
    if (!Number.isFinite(Date.parse(at))) throw new Error('Validation: invalid time');
    const key = identity(task);
    const description = task.description || '';
    const history = sessions(description);
    const open = history.find(s => s.end === null);
    if (task.status === 'COMPLETED' || task.status === 'CANCELLED') throw new Error('Conflict: finished task');
    let expected: Changes;
    if (action === 'start') {
      if (currentWorkId !== null || open) throw new Error('Conflict: current work exists');
      if (!token || !Number.isInteger(task.percentComplete) || task.percentComplete < 0 || task.percentComplete > 99 ||
          !['','NEEDS-ACTION','IN-PROCESS'].includes(task.status)) throw new Error('Validation: invalid task');
      const record: Session = {version:1, identity:key, token, start:at, beforeStatus:task.status,
        beforePercent:task.percentComplete, end:null, result:null};
      expected = {status:'IN-PROCESS', percentComplete:task.percentComplete, description:description + marker + JSON.stringify(record)};
    } else {
      if (currentWorkId !== key) throw new Error('Conflict: not current task');
      if (!open || open.identity !== key || Date.parse(at) < Date.parse(open.start)) throw new Error('Validation: missing or wrong session');
      const closed = {...open, end:at, result:action};
      const originalLine = description.split(marker).slice(1).map(part => part.split('\n')[0]!).find(line => (JSON.parse(line) as Session).token === open.token)!;
      expected = {status: action === 'stop' ? open.beforeStatus : action === 'complete' ? 'COMPLETED' : 'CANCELLED',
        percentComplete:action === 'stop' ? open.beforePercent : action === 'complete' ? 100 : task.percentComplete,
        description:description.replace(marker + originalLine, marker + JSON.stringify(closed))};
    }
    return Object.freeze({action, target:Object.freeze({calendarId:task.calendarId,id:task.id,recurrenceId:task.recurrenceId || ''}),
      expected:Object.freeze(expected), nextCurrentWorkId:action === 'start' ? key : null});
  }
  export function compare(plan: Plan, actual: Task): boolean {
    return identity(plan.target) === identity(actual) && actual.status === plan.expected.status &&
      actual.percentComplete === plan.expected.percentComplete && actual.description === plan.expected.description;
  }
}
