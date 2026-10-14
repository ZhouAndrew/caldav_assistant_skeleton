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

## Increment 7 — durable Quick Capture Outbox (2026-10-08)

Quick Captures are now written to IndexedDB before any network request, including the original text and binary file data. The independent flusher preserves insertion order, deletes an item only after the WordPress append has completed its authoritative read-back, and stops on the first failure. Captures can be queued without WordPress credentials and retried after reconnect or page reload. Concurrent retry calls share a busy guard. The UI exposes pending count and explicit retry; none of this state is consulted by CalDAV actions.

Strict compilation and 23 tests pass. The previously reported combined CI failure was an acceptance-script ambiguity after adding two fields named `url`; selectors are now scoped to the CalDAV form. The expanded browser path queues while WordPress is offline, reloads, verifies the persistent pending item, retries it, checks the direct iframe, takes WordPress offline again, then reconnects to real disposable Radicale and continues Start/Stop. This combined path awaits CI.

## Increment 8 — Today Task/Event projection (2026-10-09)

The CalDAV adapter now issues the same fail-closed REPORT pipeline for VEVENT as for VTODO. A strict read projection preserves calendar/resource identity, UID, RECURRENCE-ID, timezone-bearing DTSTART/DTEND, title and location. Missing UID/DTSTART and duplicate identities reject the scan. The Today panel reads both Task and Event directly from CalDAV and renders items matching the Asia/Shanghai calendar day; it does not create a second cache or write path.

Strict compilation and 25 tests pass. The prior Outbox CI failure was caused by the acceptance script attempting to fill controls inside a closed native `details`; the browser path now explicitly opens the same disclosure a user must open. The disposable Radicale fixture now includes a timezone-bearing VEVENT and browser acceptance verifies it in Today alongside the existing task, Outbox, iframe, offline isolation, lifecycle and uncertain-write paths. Combined CI is the next gate.

## Increment 9 — verified Event modification (2026-10-09)

Today events can now open an editor for title and location. The pure planner resolves the exact calendar/UID/RECURRENCE-ID from a freshly read resource, refuses recurring masters and exceptions, modifies only SUMMARY/LOCATION plus DTSTAMP, and preserves DTSTART/DTEND timezone parameters and all unrelated properties. The thin writer uses the fresh strong ETag, then requires both intended fields and the complete semantic VCALENDAR to match an authoritative GET before returning a receipt. Missing/replaced identities and concurrent writes fail closed.

Strict compilation and 27 tests pass, including preservation of timezone and unknown user properties plus deliberate read-back corruption. Browser acceptance updates the real disposable Radicale VEVENT and checks the verified result in Today before continuing the existing Outbox, iframe, WordPress isolation and Work recovery path. CI is the next gate. Event time editing and recurrence mutation remain intentionally unavailable until their timezone/occurrence semantics are implemented.

## Increment 10 — Record, Logs and Tools bodies (2026-10-10)

The previously pending Event-update CI run 37901029096 passed the complete Chromium/Radicale path. The standalone page now contains functional Record, Logs and Tools bodies instead of navigation-only anchors. Record submits text and attachments through the same durable WordPress Outbox as Quick Capture. Logs persist connection, workflow, Event and WordPress outcomes in IndexedDB, support scope/date/text filtering, text/JSON copy, reload and confirmed single-date clearing. Tools reports the currently discovered calendars and Task/Event counts through a deliberately read-only test; it does not create a test VEVENT in a user calendar.

Audit storage is an independent best-effort lane: failure falls back to session memory and never blocks CalDAV or WordPress. Its IndexedDB version upgrade creates both audit and capture stores regardless of which adapter opens first. Application Passwords remain session-only, and audit details contain identities/results but no credentials or resource bodies.

Strict compilation and 30 tests pass. Disposable Radicale 3.8.1 again passed canonical lifecycle, conditional write, read-back and stale-ETag preservation. The browser acceptance now covers Record append/read-back, Tools discovery output and Logs persistence across reload in addition to Event update, Outbox, iframe, WordPress isolation, currentWorkId and uncertain-write recovery. Local Chromium is unavailable, so the expanded browser path awaits remote CI.

Remaining acceptance gaps: separate-page navigation parity (the current standalone is a single-page integration), full writable Calendar diagnostic with a safely isolated target, Event time editing, recurrence mutation, and final human-path acceptance.

## Increment 11 — timezone-safe Event time editing (2026-10-10)

The first Increment 10 browser run exposed a date-sensitive test fixture, not an application read failure: its VEVENT was fixed to 2026-10-09 and therefore correctly disappeared from Today after the Asia/Shanghai date rolled over. The fixture now derives its date in the application timezone so the acceptance path remains valid across days.

The Event editor now changes DTSTART/DTEND as well as title and location. Timed events retain the original TZID and accept local wall time; all-day events retain DATE value type and explain the exclusive DTEND convention. The pure planner rejects malformed values, changing between timed/all-day representation, adding or removing DTEND implicitly, and any end not later than start. Recurring masters and exceptions remain refused. The writer still uses a fresh strong ETag and only emits a receipt after the intended local values and complete semantic VCALENDAR match an authoritative GET.

Strict compilation and 31 tests pass, including TZID preservation, all-day type preservation, invalid-range refusal and corrupted read-back refusal. Disposable Radicale 3.8.1 transport/workflow tests pass. Browser acceptance now edits a dynamically dated real VEVENT from 09:00–10:00 to 09:30–10:30 before continuing Record/Logs/Tools, WordPress isolation, Work lifecycle and uncertain-write recovery. Local Chromium download again returned an empty/truncated archive, so the expanded real browser path awaits CI.

## Increment 12 — page navigation parity and state-aware acceptance (2026-10-11)

The next browser run passed Event editing but exposed an invalid Tools expectation: after a page reload, CalDAV credentials and the in-memory transport are intentionally gone, so a connection diagnostic must not report success until the user reconnects. The acceptance path now reconnects before Tools and verifies the actual security boundary.

The six retained plugin navigation entries now switch visible standalone page bodies instead of merely scrolling a single long document. Work contains connection, Task Selector/details/actions and Quick Capture; Today contains Task/Event projection and Event editing; Record, Logs, WordPress and Tools each expose their own body. The current view is URL-hash addressable and reloadable, while credentials remain memory/session scoped exactly as before. Event editor visibility remains conditional on a selected Event and is not accidentally exposed by navigation.

Browser acceptance now follows the visible user path through Today → Work → WordPress → Work/Outbox → WordPress iframe → Record → Work reconnect → Tools → Logs/reload → WordPress failure → Work lifecycle/recovery. Hidden controls can no longer satisfy the test. Strict compilation and 31 tests pass; disposable Radicale 3.8.1 verification passes. The revised Chromium path awaits CI.

## Increment 13 — isolated writable Calendar diagnostic (2026-10-13)

The complete Increment 12 Chromium path, including response-loss recovery, passed in GitHub Actions run 38338456482. Tools now keeps its default discovery diagnostic read-only and adds a separate, explicitly confirmed writable diagnostic that will only select one VEVENT-capable calendar whose display name is exactly `CalDAV Assistant Test`. Missing, ordinary or ambiguous calendars fail closed.

The writable diagnostic creates a UUID-named temporary VEVENT with `If-None-Match: *`, performs authoritative read-back and semantic comparison, updates it with the fresh strong ETag, reads and compares again, then deletes it with `If-Match` and verifies a following GET returns Not Found. Cleanup re-reads the unique test resource to obtain its latest ETag, so a validation failure cannot leave a known temporary object merely because an earlier ETag became stale. No existing resource is selected or modified.

Strict compilation and 34 tests pass, including refusal of ordinary/ambiguous calendars and the exact create → read → update → read → delete → absence sequence. The disposable real-service and browser path is the next remote CI gate because Radicale is not installed in the local execution image.

## Increment 14 — exact recurrence-exception editing (2026-10-13)

The isolated writable diagnostic passed the complete Radicale/Chromium path in GitHub Actions run 38338888128. Event editing now permits an already-materialized VEVENT exception identified by its exact calendar, UID and RECURRENCE-ID. Only that exception component is changed; RECURRENCE-ID, the RRULE master and unrelated sibling components remain part of the full semantic read-back comparison. Title, location, local start/end and original TZID rules are the same as for non-recurring Events.

RRULE/RDATE/EXDATE masters remain deliberately blocked because changing a series requires an explicit all-occurrences versus this-and-following user choice. The browser fixture includes a master plus an existing exception and verifies editing the exception through visible Today controls against disposable Radicale.

## Increment 15 — explicit whole-series Event editing (2026-10-14)

The exact-exception and refreshed preview paths passed all workflows, including standalone HTML run 38364524829. A recurrence master can now be edited only after the user explicitly selects `整个重复系列`; the save button is disabled while scope is unset. The pure update planner independently rejects a master without `series` scope and rejects applying series scope to a non-master, so callers cannot bypass the UI guard.

Whole-series editing changes the master title, location and DTSTART/DTEND while preserving its RRULE/RDATE/EXDATE properties, existing exceptions, TZID/value type and all unrelated calendar data. Existing exception editing remains exact and single-instance. `this and following` is not guessed or simulated because interoperable range splitting requires explicit server/client semantics; it remains unavailable rather than risking silent series corruption. The disposable browser fixture now exercises both explicit whole-series and exact-exception writes with authoritative semantic read-back.
