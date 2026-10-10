import ICAL from 'ical.js';
import { CalDAVError, type Resource } from './transport.js';
import { createTransport, type Receipt } from './transport.js';
export interface CalendarEvent {
  readonly eventId:string;readonly calendarUrl:string;readonly resourceUrl:string;readonly uid:string;
  readonly recurrenceId:string|null;readonly title:string;readonly start:string;readonly end:string|null;readonly location:string;
  readonly allDay:boolean;readonly editStart:string;readonly editEnd:string;
}
function formatTime(value:ICAL.Time):string {
  const date=`${String(value.year).padStart(4,'0')}-${String(value.month).padStart(2,'0')}-${String(value.day).padStart(2,'0')}`;
  return value.isDate?date:`${date}T${String(value.hour).padStart(2,'0')}:${String(value.minute).padStart(2,'0')}`;
}
function editValue(property:ICAL.Property|null|undefined):string {return property?formatTime(property.getFirstValue() as ICAL.Time):'';}
export function projectEvents(calendarUrl:string,resource:Resource):readonly CalendarEvent[] {
  try {
    const calendar=new ICAL.Component(ICAL.parse(resource.text));
    if(calendar.name!=='vcalendar')throw new CalDAVError('Validation');
    const events=calendar.getAllSubcomponents('vevent').map(component=>{
      const uid=String(component.getFirstPropertyValue('uid')??'');const start=component.getFirstProperty('dtstart')?.toICALString();
      if(!uid||!start||component.getAllProperties('uid').length!==1)throw new CalDAVError('Validation');
      const recurrence=component.getFirstProperty('recurrence-id');const recurrenceId=recurrence?recurrence.toICALString():null;
      const startProperty=component.getFirstProperty('dtstart');const endProperty=component.getFirstProperty('dtend');
      return Object.freeze({eventId:JSON.stringify([calendarUrl,uid,recurrenceId]),calendarUrl,resourceUrl:resource.url,uid,recurrenceId,
        title:String(component.getFirstPropertyValue('summary')??''),start,end:component.getFirstProperty('dtend')?.toICALString()??null,
        location:String(component.getFirstPropertyValue('location')??''),allDay:(startProperty?.getFirstValue() as ICAL.Time).isDate,
        editStart:editValue(startProperty),editEnd:editValue(endProperty)});
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
export interface EventChanges {readonly title:string;readonly location:string;readonly start:string;readonly end:string}
function updateTime(property:ICAL.Property|null|undefined,input:string,isDate:boolean) {
  if(!property||!input)throw new CalDAVError('Validation');
  if(isDate&&!/^\d{4}-\d{2}-\d{2}$/.test(input))throw new CalDAVError('Validation');
  if(!isDate&&!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(input))throw new CalDAVError('Validation');
  const value=isDate?ICAL.Time.fromDateString(input):ICAL.Time.fromDateTimeString(`${input}:00`,property);
  if(value.isDate!==isDate||formatTime(value)!==input)throw new CalDAVError('Validation');
  property.setValue(value);return value;
}
export function planEventUpdate(selected:CalendarEvent,resource:Resource,changes:EventChanges):string {
  try {
    const projected=projectEvents(selected.calendarUrl,resource);const index=projected.findIndex(event=>event.eventId===selected.eventId);
    if(index<0)throw new CalDAVError('NotFound');
    const calendar=new ICAL.Component(ICAL.parse(resource.text));const component=calendar.getAllSubcomponents('vevent')[index]!;
    if(selected.recurrenceId!==null||component.hasProperty('rrule')||component.hasProperty('rdate'))throw new CalDAVError('Validation');
    const startProperty=component.getFirstProperty('dtstart');const endProperty=component.getFirstProperty('dtend');
    const startTime=updateTime(startProperty,changes.start,selected.allDay);
    if(Boolean(endProperty)!==Boolean(changes.end))throw new CalDAVError('Validation');
    const endTime=endProperty?updateTime(endProperty,changes.end,selected.allDay):null;
    if(endTime&&endTime.compare(startTime)<=0)throw new CalDAVError('Validation');
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
        try {const item=projectEvents(selected.calendarUrl,{...previous,text:actual}).find(event=>event.eventId===selected.eventId);return Boolean(item&&item.title===changes.title&&item.location===changes.location&&item.editStart===changes.start&&item.editEnd===changes.end&&sameCalendar(text,actual));}
        catch{return false;}
      });
    } finally {busy=false;}
  }
  return Object.freeze({update});
}
