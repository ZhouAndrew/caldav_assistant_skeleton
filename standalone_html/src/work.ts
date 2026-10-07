import ICAL from 'ical.js';
import { AssistantActionPlan as Core } from './generated-core.js';
import { CalDAVError, type Resource, type Receipt, createTransport } from './transport.js';
import { projectTasks, type Task } from './tasks.js';
export type Action = Core.Action;
function canonical(component: ICAL.Component): string {
  return JSON.stringify([component.name,
    component.getAllProperties().map(property => JSON.stringify(property.toJSON())).sort(),
    component.getAllSubcomponents().map(canonical).sort()]);
}
function sameCalendar(expected: string, actual: string): boolean {
  return canonical(new ICAL.Component(ICAL.parse(expected))) === canonical(new ICAL.Component(ICAL.parse(actual)));
}
function resolve(resource: Resource, selected: Task) {
  const tasks = projectTasks(selected.calendarUrl, resource);
  const index = tasks.findIndex(task => task.taskId === selected.taskId);
  if (index < 0) throw new CalDAVError('NotFound');
  // Recurrence mutation needs occurrence semantics; do not modify an entire recurring series.
  if (tasks[index]!.recurring || selected.recurrenceId !== null) throw new CalDAVError('Validation');
  const calendar = new ICAL.Component(ICAL.parse(resource.text));
  const component = calendar.getAllSubcomponents('vtodo')[index]!;
  const task: Core.Task = {calendarId:selected.calendarUrl,id:selected.uid,status:tasks[index]!.status,
    percentComplete:Number(component.getFirstPropertyValue('percent-complete') ?? 0),
    description:String(component.getFirstPropertyValue('description') ?? '')};
  return {calendar,component,task};
}
export function planResource(action: Action, currentWorkId: string | null, selected: Task, resource: Resource, at: string, token: string) {
  const {calendar,component,task} = resolve(resource,selected);
  const plan = Core.planWorkAction(action,currentWorkId,task,at,token);
  component.updatePropertyWithValue('status',plan.expected.status || 'NEEDS-ACTION');
  component.updatePropertyWithValue('percent-complete',plan.expected.percentComplete);
  component.updatePropertyWithValue('description',plan.expected.description);
  if (action === 'complete') component.updatePropertyWithValue('completed',ICAL.Time.fromJSDate(new Date(at),true));
  else component.removeAllProperties('completed');
  component.updatePropertyWithValue('dtstamp',ICAL.Time.fromJSDate(new Date(at),true));
  return {plan,text:calendar.toString()};
}
export interface PendingAction {
  readonly action: Action; readonly currentWorkId: string | null;
  readonly selected: Task; readonly previous: Resource; readonly at: string; readonly token: string;
}
export interface Journal {
  read(): PendingAction | null; save(value: PendingAction): void; clear(): void;
}
/** Effects are serialized. Pointer publication occurs only after authoritative validation. */
export function createWork(transport: ReturnType<typeof createTransport>, state: {
  read(): string | null; publish(value: string | null): void;
}, journal?: Journal) {
  let busy = false;
  async function run(action: Action, selected: Task, at: string, token: string): Promise<Receipt> {
    if (busy) throw new CalDAVError('Conflict');
    busy = true;
    try {
      if (journal?.read()) throw new CalDAVError('Conflict');
      const previous = await transport.read(selected.resourceUrl);
      const {plan,text} = planResource(action,state.read(),selected,previous,at,token);
      // Persist intent before PUT; crashes and uncertain responses remain recoverable.
      journal?.save({action,currentWorkId:state.read(),selected,previous,at,token});
      const receipt = await transport.writeVerified(selected.resourceUrl,text,previous.etag,(_expected,actual) => {
        try {
          const result = resolve({...previous,text:actual},selected);
          return Core.compare(plan,result.task) && sameCalendar(text,actual);
        } catch { return false; }
      });
      state.publish(plan.nextCurrentWorkId);
      journal?.clear();
      return receipt;
    } finally { busy = false; }
  }
  async function recover(): Promise<'none' | 'applied' | 'unchanged'> {
    if (busy) throw new CalDAVError('Conflict');
    busy = true;
    try {
      const pending = journal?.read();
      if (!pending) return 'none';
      const {action,currentWorkId,selected,previous,at,token} = pending;
      const {plan,text} = planResource(action,currentWorkId,selected,previous,at,token);
      // Read-only recovery: never repeat PUT or infer success from status alone.
      const actual = await transport.read(selected.resourceUrl);
      if (sameCalendar(text,actual.text) && Core.compare(plan,resolve(actual,selected).task)) {
        state.publish(plan.nextCurrentWorkId);
        journal!.clear();
        return 'applied';
      }
      if (actual.etag === previous.etag && sameCalendar(previous.text,actual.text)) {
        journal!.clear();
        return 'unchanged';
      }
      throw new CalDAVError('Conflict');
    } finally { busy = false; }
  }
  return Object.freeze({run,recover});
}
