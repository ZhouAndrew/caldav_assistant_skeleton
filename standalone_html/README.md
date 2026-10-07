# CalDAV Assistant standalone HTML migration

Status: first transport increment implemented; no standalone application/UI acceptance yet.

The user explicitly changed the Thunderbird-only scope on 2026-10-07: retain all existing plugin pages and interactions as independent HTML + JS, implement independent CalDAV access and a CalDAV-backed Task Selector. This supersedes the Thunderbird-only/native Tasks selection constraints for this directory. It does not change CLI/Public Python API contracts.

Preserve currentWorkId, Start/Stop/Complete/Cancel, pure functional core with a thin effect boundary, and write → read back → compare → receipt. WordPress remains independent output. Preserve Quick Capture, Open Post and independent full Post iframe preview.

## Increment 1 — HTTP boundary

`src/transport.ts` is browser-compatible TypeScript with an injected fetch boundary. It supports authenticated requests (including PROPFIND/REPORT), authoritative GET with strong ETag, conditional PUT creation/update and caller-supplied pure read-back validation. Credentials stay in memory; errors omit response bodies and network exception details. Foreign-origin URLs and redirects are refused. No currentWorkId is published here.

Run `npm ci` then `npm test` (TypeScript 5.9.3). For real integration, start an isolated disposable Radicale and run:

```sh
CALDAV_TEST_URL=http://127.0.0.1:5232/test/ node tests/real-radicale.mjs
```

The integration fixture uses test:test Basic credentials, creates a unique calendar, and deletes only that calendar afterward. Do not point this fixture at a production server.

## Evidence — 2026-10-07

Baseline: main b9dcffd. Strict compilation and 7 transport tests passed. Real Radicale 3.8.1 on loopback passed PROPFIND, MKCALENDAR, create/read-back, update/read-back, stale ETag rejection and preservation of the newer server data. Test collection was removed.

This validates HTTP transport under Node's fetch, not browser CORS/TLS or the full application. The comparator in the integration fixture checks SUMMARY only; production workflow validation must compare all intended domain fields. Certificate trust stays governed by the browser.

## Next increments

1. Calendar discovery and namespace-aware XML parsing with partial-scan/error handling.
2. iCalendar parsing with recurrence/timezone-preserving identity; CalDAV Task Selector outputs taskId only.
3. Migrate all plugin pages without redesign; wire independent adapters/storage and existing pure action semantics.
4. Migrate WordPress output/Outbox, Quick Capture and Post preview. Read latest preview branch before moving UI; it is not yet incorporated into this transport branch.
5. Browser and real service human-path acceptance, restart recovery, conflict and offline tests.

No plugin UI or stable XPI bytes were changed by this increment.

## Increment 2 — discovery and selector (2026-10-07)

Implemented namespace-aware, fail-closed WebDAV multistatus parsing; principal → calendar-home → calendar discovery; VTODO REPORT; pure task projections with calendar/UID/RECURRENCE-ID identity and preserved timezone/date-only metadata. Recurring masters are marked and are not expanded or guessed as instances. Missing fields, duplicate identities and partial server failures reject the entire scan.

`selector.html` is a standalone read-only integration page using the existing workspace stylesheet. It connects, discovers calendars, lists unfinished tasks, searches and emits `task-selected` with taskId only. It does not implement workflow actions yet, and does not claim that all plugin pages have migrated. Credentials are kept in memory. A static server must serve this directory after `npm ci && npm test`; opening via file:// is not the supported module path.

11 tests and strict application typecheck pass. The iCalendar dependency's declarations require skipLibCheck; application strict checks remain enabled. Real Radicale 3.8.1 discovery/REPORT and task projection passed in addition to the transport checks. Browser human-path test is implemented in tests/browser.mjs; browser installation/testing and remote CI are the next acceptance gate.

Reproduce service tests with `python tests/run-services.py` after installing Radicale 3.8.1. Add `--browser` after `npx playwright install chromium` for actual connect/search/select against real disposable Radicale with explicit CORS configuration. The new standalone-html GitHub workflow runs these checks. No production server or user data is accessed.
