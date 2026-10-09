import ICAL from 'ical.js';
import { CalDAVError, type Resource } from './transport.js';
import { createTransport, type Receipt } from './transport.js';
export interface CalendarEvent {
  readonly eventId:string;readonly calendarUrl:string;readonly resourceUrl:string;readonly uid:string;
  readonly recurrenceId:string|null;readonly title:string;readonly start:string;readonly end:string|null;readonly location:string;
}
export function projectEvents(calendarUrl:string,resource:Resource):readonly CalendarEvent[] {
  try {
    const calendar=new ICAL.Component(ICAL.parse(resource.text));
    if(calendar.name!=='vcalendar')throw new CalDAVError('Validation');
    const events=calendar.getAllSubcomponents('vevent').map(component=>{
      const uid=String(component.getFirstPropertyValue('uid')??'');const start=component.getFirstProperty('dtstart')?.toICALString();
      if(!uid||!start||component.getAllProperties('uid').length!==1)throw new CalDAVError('Validation');
      const recurrence=component.getFirstProperty('recurrence-id');const recurrenceId=recurrence?recurrence.toICALString():null;
      return Object.freeze({eventId:JSON.stringify([calendarUrl,uid,recurrenceId]),calendarUrl,resourceUrl:resource.url,uid,recurrenceId,
        title:String(component.getFirstPropertyValue('summary')??''),start,end:component.getFirstProperty('dtend')?.toICALString()??null,
        location:String(component.getFirstPropertyValue('location')??'')});
    });
    if(new Set(events.map(event=>event.eventId)).size!==events.length)throw new CalDAVError('Validation');
    return Object.freeze(events);
  } catch {throw new CalDAVError('Validation');}
}
export function occursOn(event:CalendarEvent,day:string):boolean {
  return propertyDay(event.start)===day;
}
export function propertyDay(value:string|null):string|null {
  const match=value?.match(/(\d{4})(\d{2})(\d{2})(?:T|$)/);return match?`${match[1]}-${match[2]}-${match[3]}`:null;
}
function canonical(component:ICAL.Component):string {
  return JSON.stringify([component.name,component.getAllProperties().map(property=>JSON.stringify(property.toJSON())).sort(),component.getAllSubcomponents().map(canonical).sort()]);
}
function sameCalendar(expected:string,actual:string) {
  return canonical(new ICAL.Component(ICAL.parse(expected)))===canonical(new ICAL.Component(ICAL.parse(actual)));
}
export interface EventChanges {readonly title:string;readonly location:string}
export function planEventUpdate(selected:CalendarEvent,resource:Resource,changes:EventChanges):string {
  try {
    const projected=projectEvents(selected.calendarUrl,resource);const index=projected.findIndex(event=>event.eventId===selected.eventId);
    if(index<0)throw new CalDAVError('NotFound');
    const calendar=new ICAL.Component(ICAL.parse(resource.text));const component=calendar.getAllSubcomponents('vevent')[index]!;
    if(selected.recurrenceId!==null||component.hasProperty('rrule')||component.hasProperty('rdate'))throw new CalDAVError('Validation');
    component.updatePropertyWithValue('summary',changes.title);
    if(changes.location)component.updatePropertyWithValue('location',changes.location);else component.removeAllProperties('location');
    component.updatePropertyWithValue('dtstamp',ICAL.Time.fromJSDate(new Date(),true));
    return calendar.toString();
  } catch(error) {if(error instanceof CalDAVError)throw error;throw new CalDAVError('Validation');}
}
export function createEventWriter(transport:ReturnType<typeof createTransport>) {
  let busy=false;
  async function update(selected:CalendarEvent,changes:EventChanges):Promise<Receipt> {
    if(busy)throw new CalDAVError('Conflict');busy=true;
    try {
      const previous=await transport.read(selected.resourceUrl);const text=planEventUpdate(selected,previous,changes);
      return await transport.writeVerified(selected.resourceUrl,text,previous.etag,(_expected,actual)=>{
        try {const item=projectEvents(selected.calendarUrl,{...previous,text:actual}).find(event=>event.eventId===selected.eventId);return Boolean(item&&item.title===changes.title&&item.location===changes.location&&sameCalendar(text,actual));}
        catch{return false;}
      });
    } finally {busy=false;}
  }
  return Object.freeze({update});
}
