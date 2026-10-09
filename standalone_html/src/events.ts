import ICAL from 'ical.js';
import { CalDAVError, type Resource } from './transport.js';
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
