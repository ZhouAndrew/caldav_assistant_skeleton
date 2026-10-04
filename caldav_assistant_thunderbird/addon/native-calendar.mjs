// Native Thunderbird provider adapter, referenced only from the experiment.
import {cal} from 'resource:///modules/calendar/calUtils.sys.mjs';
function nativeId(item) { return JSON.stringify([item.calendar.id,item.id,item.recurrenceId?.icalString ?? null]); }
function snapshot(item) {
  return {id:nativeId(item),calendarId:item.calendar.id,title:item.title ?? '',status:item.getProperty('STATUS'),percentComplete:item.getProperty('PERCENT-COMPLETE') == null ? null : Number(item.percentComplete),description:item.getProperty('DESCRIPTION') ?? '',completedAt:item.completedDate ? cal.dtz.dateTimeToJsDate(item.completedDate).toISOString() : null,revision:item.icalString,readOnly:item.calendar.readOnly || Boolean(item.recurrenceInfo && !item.recurrenceId),recurring:Boolean(item.recurrenceInfo || item.recurrenceId)};
}
async function resolve(id) {
  const [calendarId,uid,recurrenceId] = JSON.parse(id);
  const calendar = cal.manager.getCalendarById(calendarId);
  if (!calendar) throw new Error('CALENDAR_NOT_FOUND');
  const parent = await calendar.getItem(uid);
  if (!parent || !parent.isTodo()) throw new Error('TASK_NOT_FOUND');
  const item = recurrenceId ? parent.recurrenceInfo?.getOccurrenceFor(cal.createDateTime(recurrenceId)) : parent;
  if (!item) throw new Error('OCCURRENCE_NOT_FOUND');
  return {calendar,parent,item};
}
export const nativeTasks = {
  async get(id) { return snapshot((await resolve(id)).item); },
  async list(settings={}) {
    const results = [];
    for (const calendar of cal.manager.getCalendars()) {
      if (calendar.getProperty('disabled') || calendar.getProperty('capabilities.tasks.supported') === false || settings.calendarId && settings.calendarId !== calendar.id) continue;
      const reader = calendar.getItems(Ci.calICalendar.ITEM_FILTER_TYPE_TODO | Ci.calICalendar.ITEM_FILTER_COMPLETED_ALL,0,null,null).getReader();
      try { while (true) {const {value,done} = await reader.read(); if (done) break; for (const item of Array.isArray(value) ? value : [value]) {
        if (!item.recurrenceInfo) results.push(snapshot(item));
        else {
          const from=cal.dtz.jsDateToDateTime(new Date(settings.rangeStart ?? Date.now()-30*86400000));
          const until=cal.dtz.jsDateToDateTime(new Date(settings.rangeEnd ?? Date.now()+90*86400000));
          const occurrences=item.recurrenceInfo.getOccurrences(from,until,5000);
          if(occurrences.length===5000)throw new Error('RECURRENCE_RANGE_TOO_LARGE');
          for(const occurrence of occurrences){const row=snapshot(occurrence);row.title+=` · ${occurrence.recurrenceId.icalString}`;results.push(row);}
          for (const rid of item.recurrenceInfo.getExceptionIds()) results.push(snapshot(item.recurrenceInfo.getExceptionFor(rid)));
        }
      }} } finally {reader.releaseLock();}
    }
    return [...new Map(results.map(row=>[row.id,row])).values()];
  },
  async write(id,patch,revision) {
    const {calendar,parent,item} = await resolve(id);
    if (calendar.readOnly) throw new Error('READ_ONLY_TASK');
    if (item.icalString !== revision) throw new Error('TASK_REVISION_CONFLICT');
    if (item.recurrenceInfo && !item.recurrenceId) throw new Error('SELECT_RECURRING_OCCURRENCE');
    const next = item.clone();
    for (const [key,property] of [['status','STATUS'],['percentComplete','PERCENT-COMPLETE'],['description','DESCRIPTION']]) if (key in patch) {
      if (patch[key] == null) next.deleteProperty(property); else next.setProperty(property,patch[key]);
    }
    // Omitting timezone uses UTC date components. Passing UTC would reinterpret
    // local components as UTC on machines outside UTC (Thunderbird's API contract).
    if ('completedAt' in patch) next.completedDate = patch.completedAt ? cal.dtz.jsDateToDateTime(new Date(patch.completedAt)) : null;
    if (item.recurrenceId) {const master = parent.clone(); master.recurrenceInfo.modifyException(next,true); await calendar.modifyItem(master,parent);}
    else await calendar.modifyItem(next,item);
  }
};
