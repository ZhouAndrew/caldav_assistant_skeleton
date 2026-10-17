import ICAL from 'ical.js';
import { CalDAVError, createTransport } from './transport.js';
import type { Calendar } from './caldav.js';

export const DIAGNOSTIC_CALENDAR_NAME='CalDAV Assistant Test';
function canonical(text:string):string {
  const normalize=(component:ICAL.Component):string=>JSON.stringify([component.name,
    component.getAllProperties().map(property=>JSON.stringify(property.toJSON())).sort(),
    component.getAllSubcomponents().map(normalize).sort()]);
  return normalize(new ICAL.Component(ICAL.parse(text)));
}
export function selectDiagnosticCalendar(calendars:readonly Calendar[]):Calendar {
  const matches=calendars.filter(calendar=>calendar.name===DIAGNOSTIC_CALENDAR_NAME&&
    (!calendar.components.length||calendar.components.includes('VEVENT')));
  if(matches.length!==1) throw new CalDAVError('Validation');
  return matches[0]!;
}
export async function runWritableDiagnostic(transport:ReturnType<typeof createTransport>,calendars:readonly Calendar[],token:string,at:string) {
  if(!/^[0-9a-f-]{16,64}$/i.test(token)||!Number.isFinite(Date.parse(at))) throw new CalDAVError('Validation');
  const calendar=selectDiagnosticCalendar(calendars);const stamp=at.replace(/[-:]/g,'').replace(/\.\d{3}Z$/,'Z');
  const url=new URL(`caldav-assistant-diagnostic-${token}.ics`,calendar.url).href;
  const initial=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//CalDAV Assistant Diagnostic//EN','BEGIN:VEVENT',`UID:${token}@caldav-assistant.invalid`,`DTSTAMP:${stamp}`,`DTSTART:${stamp}`,'DURATION:PT1M','SUMMARY:CalDAV Assistant diagnostic create','END:VEVENT','END:VCALENDAR',''].join('\r\n');
  let attempted=false;
  try {
    attempted=true;
    const created=await transport.writeVerified(url,initial,null,(expected,actual)=>canonical(expected)===canonical(actual));
    const component=new ICAL.Component(ICAL.parse(created.resource.text));component.getFirstSubcomponent('vevent')!.updatePropertyWithValue('summary','CalDAV Assistant diagnostic update');
    const updatedText=component.toString();
    const updated=await transport.writeVerified(url,updatedText,created.resource.etag,(expected,actual)=>canonical(expected)===canonical(actual));
    const deleted=await transport.deleteVerified(url,updated.resource.etag);attempted=false;
    return Object.freeze({verified:true as const,calendarUrl:calendar.url,resourceUrl:url,steps:Object.freeze(['create-read-compare','update-read-compare','delete-read-404']),deleted:deleted.verified});
  } finally {
    if(attempted) { try { const fresh=await transport.read(url);await transport.deleteVerified(url,fresh.etag); } catch { /* Missing or already deleted; report the primary result. */ } }
  }
}
