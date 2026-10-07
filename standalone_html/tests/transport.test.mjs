import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createTransport } from '../.build/transport.js';
const baseUrl = 'https://calendar.example/user/';
const response = (text = 'task', status = 200, etag = '"v1"') => new Response(text, { status, headers: { ETag: etag } });
test('conditional write reads back before issuing receipt', async () => {
  const calls = [];
  const transport = createTransport({ baseUrl, authorization: 'Basic test', fetch: async (url, init) => {
    calls.push({ url, ...init }); return response();
  }});
  const receipt = await transport.writeVerified('task.ics', 'task', '"v0"', (a,b) => a === b);
  assert.equal(receipt.verified, true);
  assert.deepEqual(calls.map(c => c.method), ['PUT', 'GET']);
  assert.equal(calls[0].headers.get('If-Match'), '"v0"');
  assert.equal(calls[0].redirect, 'error');
});
test('creation never overwrites an existing resource', async () => {
  const transport = createTransport({ baseUrl, fetch: async (_, init) => {
    if (init.method === 'PUT') assert.equal(init.headers.get('If-None-Match'), '*');
    return response();
  }});
  await transport.writeVerified('task.ics', 'task', null, (a,b) => a === b);
});
test('mismatch produces no success receipt', async () => {
  const transport = createTransport({ baseUrl, fetch: async () => response('different') });
  await assert.rejects(transport.writeVerified('task.ics', 'task', '"v0"', (a,b) => a === b), { code: 'Validation' });
});
test('conflict stops before read-back', async () => {
  let calls = 0;
  const transport = createTransport({ baseUrl, fetch: async () => { calls++; return response('', 412); } });
  await assert.rejects(transport.writeVerified('task.ics', 'task', '"v0"', () => true), { code: 'Conflict' });
  assert.equal(calls, 1);
});
test('foreign origin never receives credentials', async () => {
  let calls = 0;
  const transport = createTransport({ baseUrl, authorization: 'secret', fetch: async () => { calls++; return response(); } });
  await assert.rejects(transport.read('https://other.example/task'), { code: 'Validation' });
  assert.equal(calls, 0);
});
test('network exceptions are redacted; authentication classified', async () => {
  const transport = createTransport({ baseUrl, fetch: async () => { throw Error('secret'); } });
  await assert.rejects(transport.read('task'), { code: 'Unavailable', message: 'CalDAV Unavailable' });
  const denied = createTransport({ baseUrl, fetch: async () => response('', 401) });
  await assert.rejects(denied.read('task'), { code: 'Permission' });
});
test('missing or weak ETag cannot be used for safe updates', async () => {
  for (const etag of ['', 'W/"v1"']) {
    const transport = createTransport({ baseUrl, fetch: async () => response('task', 200, etag) });
    await assert.rejects(transport.read('task'), { code: 'Validation' });
  }
});
