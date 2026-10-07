import assert from 'node:assert/strict';
import { createTransport } from '../.build/transport.js';
const baseUrl = process.env.CALDAV_TEST_URL;
if (!baseUrl) throw Error('Set CALDAV_TEST_URL to an isolated disposable Radicale server');
const transport = createTransport({ baseUrl, fetch, authorization: 'Basic ' + Buffer.from('test:test').toString('base64') });
await transport.request('PROPFIND', './', '<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>', { Depth: '0' });
const calendar = `transport-test-${crypto.randomUUID()}/`;
await transport.request('MKCALENDAR', calendar, '<?xml version="1.0"?><c:mkcalendar xmlns:c="urn:ietf:params:xml:ns:caldav"><d:set xmlns:d="DAV:"><d:prop><d:resourcetype><d:collection/><c:calendar/></d:resourcetype></d:prop></d:set></c:mkcalendar>');
try {
  const href = `${calendar}task.ics`;
  const text = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//CalDAV Assistant transport test//EN\r\nBEGIN:VTODO\r\nUID:transport-test\r\nDTSTAMP:20261007T000000Z\r\nSUMMARY:Transport test\r\nSTATUS:NEEDS-ACTION\r\nEND:VTODO\r\nEND:VCALENDAR\r\n';
  const sameSummary = (expected, actual) => actual.includes(expected.match(/SUMMARY:[^\r\n]*/)[0]);
  const created = await transport.writeVerified(href, text, null, sameSummary);
  assert.equal(created.verified, true);
  const updated = await transport.writeVerified(href, text.replace('SUMMARY:Transport test', 'SUMMARY:Updated'), created.resource.etag, sameSummary);
  assert.notEqual(updated.resource.etag, created.resource.etag);
  await assert.rejects(transport.writeVerified(href, text, created.resource.etag, sameSummary), { code: 'Conflict' });
  assert.match((await transport.read(href)).text, /SUMMARY:Updated/);
  console.log('PASS real Radicale: create/read-back/update/read-back/stale ETag rejection/data preservation');
} finally {
  await transport.request('DELETE', calendar);
}
