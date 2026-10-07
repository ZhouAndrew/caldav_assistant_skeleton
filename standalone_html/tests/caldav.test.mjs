import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DOMParser } from '@xmldom/xmldom';
import { parseMultistatus, createCalDAV } from '../.build/caldav.js';
import { createTransport } from '../.build/transport.js';
import { projectTasks, selectTasks } from '../.build/tasks.js';
export const parseXML = text => new DOMParser({ onError: () => { throw Error('invalid XML'); } }).parseFromString(text, 'application/xml');
const wrap = content => `<multistatus xmlns="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">${content}</multistatus>`;
const entry = (href, props, status = 200) => `<response><href>${href}</href><propstat><prop>${props}</prop><status>HTTP/1.1 ${status} Test</status></propstat></response>`;
test('XML namespace prefixes do not determine meaning; failed scans rejected', () => {
  assert.equal(parseMultistatus(wrap(entry('/a/', '<displayname>A &amp; B</displayname>')), parseXML)[0].props.textContent, 'A & B');
  assert.throws(() => parseMultistatus(wrap(entry('/a/', '<displayname/>', 500)), parseXML), { code: 'Unavailable' });
  assert.throws(() => parseMultistatus('<!DOCTYPE x><x/>', parseXML), { code: 'Validation' });
  assert.throws(() => parseMultistatus('<bad>', parseXML), { code: 'Validation' });
});
test('discovery follows principal/home and only returns calendars', async () => {
  const replies = [wrap(entry('/user/', '<current-user-principal><href>/principal/</href></current-user-principal>')),
    wrap(entry('/principal/', '<c:calendar-home-set><href>/home/</href></c:calendar-home-set>')),
    wrap(entry('/home/', '<resourcetype><collection/></resourcetype>') + entry('/home/tasks/', '<resourcetype><collection/><c:calendar/></resourcetype><displayname>Tasks</displayname><c:supported-calendar-component-set><c:comp name="VTODO"/></c:supported-calendar-component-set>'))];
  const transport = createTransport({ baseUrl: 'https://test.example/user/', fetch: async () => new Response(replies.shift(), {status:207}) });
  const calendars = await createCalDAV(transport, 'https://test.example/user/', parseXML).discover();
  assert.deepEqual(calendars, [{url:'https://test.example/home/tasks/',name:'Tasks',components:['VTODO']}]);
});
test('task identities preserve calendar and recurrence timezone', () => {
  const text = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:one\r\nSUMMARY:Folded long\r\n  title\r\nRECURRENCE-ID;TZID=Asia/Taipei:20261007T090000\r\nDUE;VALUE=DATE:20261008\r\nEND:VTODO\r\nEND:VCALENDAR\r\n';
  const tasks = projectTasks('https://test/calendar/', { url:'https://test/task.ics',etag:'"1"',text });
  assert.equal(tasks[0].title, 'Folded long title');
  assert.match(tasks[0].recurrenceId, /TZID=Asia\/Taipei/);
  assert.match(tasks[0].due, /VALUE=DATE/);
  assert.equal(selectTasks(tasks,'folded').length,1);
  assert.equal(selectTasks([{...tasks[0],status:'COMPLETED'}],'').length,0);
  assert.notEqual(tasks[0].taskId,projectTasks('https://test/other/', {url:'https://test/task.ics',etag:'"1"',text})[0].taskId);
});
test('duplicate identities refuse ambiguous task selection', () => {
  const text = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + 'BEGIN:VTODO\r\nUID:one\r\nEND:VTODO\r\n'.repeat(2) + 'END:VCALENDAR\r\n';
  assert.throws(() => projectTasks('https://test/calendar/', {url:'https://test/task.ics',etag:'"1"',text}), {code:'Validation'});
});
