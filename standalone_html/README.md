# CalDAV Assistant standalone HTML migration

Status: CalDAV transport, discovery, selector, verified work actions and recovery are browser-tested; standalone Workspace/WordPress migration is in progress.

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

## Increment 3 — selected task details and reuse (2026-10-07)

Selection still emits taskId only. A thin reader re-fetches the selected resource, resolves its exact calendar/UID/RECURRENCE-ID with the existing ical.js parser, and displays current title, status, date metadata and original description as text. Deleted/replaced identities fail closed. Reconnects and newer selections invalidate earlier responses. This is a read-only increment: workflow actions and full plugin page migration remain outstanding.

Strict TypeScript compilation and 12 tests passed, including exact identity rejection and description preservation. Disposable real Radicale 3.8.1 transport/discovery checks passed again. Browser script now checks selected detail rendering, but could not execute here: Playwright Chromium is absent and its download repeatedly returned invalid/truncated archives. No browser acceptance is claimed.

Root LICENSE was synchronized from current upstream main (GNU GPL version 3). Runtime iCalendar parsing continues to reuse ical.js 2.2.1, whose MPL-2.0 notice is preserved in THIRD_PARTY/ical.js-LICENSE; do not relabel third-party code. Future deliverables must retain notices and corresponding source/build instructions.

Next concrete step: finish browser acceptance, then wire the existing pure action core through the independent CalDAV adapter with full intended-field verification before publishing currentWorkId.

## Increment 4 — reuse canonical work core (2026-10-07)

The standalone build generates an ES module from the unchanged canonical Thunderbird TypeScript core. There is no second implementation of action rules. The adapter reads fresh server data, plans Start/Stop/Complete/Cancel, conditionally writes using ETag, then checks the canonical workflow fields and the complete semantic iCalendar structure before publishing currentWorkId. Property/component ordering may normalize; loss or changes to unrelated data reject validation. Recurring series and recurrence exceptions refuse mutation until occurrence behavior is implemented.

The selector preview now exposes four actions. currentWorkId is persisted per server origin and username; credentials are not persisted. Selection and reconnection cannot interrupt an in-flight work action. This remains an incremental preview, not a complete migration or approved release.

Strict compilation and 16 tests pass. Real disposable Radicale start/stop/restart/complete and start/cancel pass alongside discovery, read-back and stale-ETag protection. Browser automation includes start/stop but remains unexecuted locally because Chromium is unavailable. Restart recovery, uncertain writes, full page migration and WordPress migration remain acceptance gates.

Build a preview with `python scripts/build-preview.py` after `npm test`. Each archive has a unique name and BUILD.json, compiled modules, the local ical.js runtime, notices and rebuilding sources. Run the static server as described in START.txt. Browser CORS and certificate trust still apply.

## Increment 5 — durable uncertain-write recovery (2026-10-07)

Before a workflow PUT, the browser persists a per-account pending intent containing the original resource, action inputs and session token (never credentials). A verified receipt publishes currentWorkId and clears intent. Failed or interrupted writes disable actions until reconnection. Recovery only performs GET: it re-plans through the canonical pure core and compares the entire semantic calendar plus workflow fields before publishing. An unchanged original ETag/content clears an unapplied intent; divergent server data retains the record and blocks mutation. Storage failure before intent persistence prevents PUT; failure after server commit remains recoverable. Connections are serialized while recovery runs.

Strict compilation and 19 tests passed, covering lost responses for all four actions, refusal to repeat pending writes, conflicting external changes and local persistence failures. Disposable real Radicale transport/workflow integration passed. Browser acceptance now covers reload with current work and a server-committed PUT whose response is deliberately dropped; this new browser path awaits execution/CI. Earlier connect/search/select CI run 37564294588 is confirmed successful, but is not evidence for these new paths.

Full plugin UI, Event editing, recurrence mutation and independent WordPress/Quick Capture/Post preview migration remain incomplete. Next: confirm new browser recovery acceptance, then migrate the existing workspace pages and independent output adapters.

## Increment 6 — Workspace capture and independent Post preview (2026-10-08)

The recovery browser path passed in GitHub Actions run 37597337290: real Chromium and disposable Radicale verified connect, selection, lifecycle, reload, deliberately lost PUT response and read-only recovery.

The standalone Work page now retains the plugin navigation and adds its Quick Capture, Open Post and full iframe preview panels. A separate browser REST adapter finds or creates the exact daily Post, uploads pasted/dropped files, appends an escaped marker-bearing block and reads the Post back before success. Duplicate daily Posts fail closed. The iframe reads the Post directly from its public link. CalDAV never imports or awaits this adapter; WordPress errors are reported only in their own panels. URL and username may persist locally, while the Application Password is session-only.

Strict compilation and 22 tests pass, including output escaping, duplicate detection and create/upload/append/read-back. Browser acceptance now mocks the WordPress server to test capture and the full iframe, deliberately takes WordPress offline, and then continues the real Radicale Start/Stop path. This new combined browser path awaits CI. Independent durable WordPress Outbox, the remaining Today/Record/Logs/WordPress/Tools pages, Event editing and recurrence mutation remain incomplete.
