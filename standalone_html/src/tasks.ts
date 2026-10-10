import ICAL from 'ical.js';
import { CalDAVError, type Resource } from './transport.js';
export interface Task {
  readonly taskId: string; readonly calendarUrl: string; readonly resourceUrl: string;
  readonly uid: string; readonly recurrenceId: string | null; readonly title: string;
  readonly status: string; readonly due: string | null; readonly recurring: boolean;
}
/** Read projection only. Recurring masters are identified, never guessed as occurrences. */
export function projectTasks(calendarUrl: string, resource: Resource): readonly Task[] {
  try {
    const calendar = new ICAL.Component(ICAL.parse(resource.text));
    if (calendar.name !== 'vcalendar') throw new CalDAVError('Validation');
    const tasks = calendar.getAllSubcomponents('vtodo').map(component => {
      const uid = String(component.getFirstPropertyValue('uid') ?? '');
      if (!uid || component.getAllProperties('uid').length !== 1) throw new CalDAVError('Validation');
      const recurrence = component.getFirstProperty('recurrence-id');
      const recurrenceId = recurrence ? recurrence.toICALString() : null;
      return Object.freeze({ taskId: JSON.stringify([calendarUrl, uid, recurrenceId]), calendarUrl, resourceUrl: resource.url,
        uid, recurrenceId, title: String(component.getFirstPropertyValue('summary') ?? ''),
        status: String(component.getFirstPropertyValue('status') ?? 'NEEDS-ACTION').toUpperCase(),
        due: component.getFirstProperty('due')?.toICALString() ?? null,
        recurring: component.hasProperty('rrule') || component.hasProperty('rdate') });
    });
    if (new Set(tasks.map(task => task.taskId)).size !== tasks.length) throw new CalDAVError('Validation');
    return Object.freeze(tasks);
  } catch { throw new CalDAVError('Validation'); }
}
export function selectTasks(tasks: readonly Task[], query: string, includeFinished = false): readonly Task[] {
  const text = query.trim().toLocaleLowerCase();
  return tasks.filter(task => (includeFinished || !['COMPLETED', 'CANCELLED'].includes(task.status)) && task.title.toLocaleLowerCase().includes(text));
}

export interface TaskDetails {
  readonly task: Task;
  readonly description: string;
}
/** Resolve a selector identity from a fresh resource; never trust a cached title/status. */
export function readTaskDetails(calendarUrl: string, resource: Resource, taskId: string): TaskDetails {
  const projected = projectTasks(calendarUrl, resource);
  const index = projected.findIndex(task => task.taskId === taskId);
  if (index < 0) throw new CalDAVError('NotFound');
  const component = new ICAL.Component(ICAL.parse(resource.text)).getAllSubcomponents('vtodo')[index]!;
  return Object.freeze({ task: projected[index]!, description: String(component.getFirstPropertyValue('description') ?? '') });
}
