# CalDAV Assistant: functional Thunderbird rebuild

This is a from-zero replacement for the previous Thunderbird add-on, based on
`FUNCTIONAL_VTODO_REFACTOR.md` and Thunderbird's own Calendar APIs. The original
add-on implementation, helpers, typed legacy state machine and its tests were
removed from this branch. None of those modules is imported by the replacement.

## Install the candidate

In Thunderbird, open Add-ons Manager → the gear menu → Install Add-on From File,
and select `artifacts/CalDAV-Assistant-cleanroom-0.4.0-candidate.xpi`.
The add-on identity remains `ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net`
so upgrading replaces the previous implementation and retains extension storage.
Choose CalDAV Assistant in the Spaces toolbar. Task selection only opens a task;
Start/Stop/Complete/Cancel live on the selected task page.

WordPress settings have normal form fields. Records are saved as drafts. When
WordPress is enabled, closed work periods are durably queued before sending.
WordPress delivery, including connection/full-write tests, cannot lock Task
commands. Pending records are retried at startup, every five minutes and through
an explicit retry button. Auto uses REST first and can fall back to configured
WP-CLI on network/401/403 errors. Explicit REST never falls back.

## Implementation boundary

- `domain.mjs`: pure Description parser/serializer, transitions, view models and transport policy.
- `views.mjs`: pure page functions returning view descriptors.
- `page.mjs`: route/query/render and explicit user command effects.
- `services.mjs`: one Task command queue; VTODO write/read-back; pointer commit;
  durable pending-write receipt and independent WordPress delivery queue.
- `native-calendar.mjs`: Thunderbird Calendar provider reads and revision-checked
  writes, including recurrence exceptions. No second CalDAV client.
- `native-wordpress.mjs`: native Subprocess calls to WP-CLI with argument arrays;
  no shell command construction.
- `store.mjs`: pointer, settings, diagnostics, Outbox and transient write receipts;
  serialized Outbox updates protect concurrent append and delivery.
- `migration.mjs`: isolated once-only persisted-data conversion. Missing legacy
  evidence stops migration visibly; it never invents a Start baseline. User
  Description and queued records are retained. After verification, old runtime
  and audit storage are removed; historical receipts become diagnostic history.

There is no Work VEVENT creation, Pause/Resume/Switch Away, audit-derived work
state, legacy runtime module, Native Host, Python bridge or task-state database.
Generic Task/Event functionality in the wider Python project is unchanged.
Recurring tasks are presented as occurrences in a default window of 30 past and
90 future days; stored exceptions remain discoverable outside that window.

## Real acceptance

The tests use disposable profiles and disposable servers. Fixture tasks model
Unicode/multiline descriptions, existing 35% progress, date-only due fields and
recurrence; they are not an export of the user's private data.

`tests/real_thunderbird.py` installs the actual packaged XPI in Thunderbird
153.1.0esr, drives real production DOM click events using Marionette and test-only
JSWindowActors, and uses a real Radicale server. It independently reads the
resulting VTODOs over HTTP. It also checks a genuine application restart,
occurrence isolation, read-only pages, WordPress failure/Outbox retry through
Thunderbird's actual native WP-CLI adapter, and one-time migration against native
VTODOs and actual extension storage. Test actors are not in the production XPI.

`tests/wordpress-real.mjs` exercises actual local WordPress with its official
SQLite integration, actual REST responses, and actual WP-CLI processes. It
checks draft/media CRUD and cleanup, authentication and permission failures,
strict/automatic transports, durable offline records and retry deduplication.

For a Linux test machine with Node 24, Python 3.12 and PHP with sqlite3/pdo_sqlite:

```bash
python -m pip install radicale==3.8.1 marionette_driver==3.7.1 requests
python caldav_assistant_thunderbird/tests/prepare_fixtures.py
python caldav_assistant_thunderbird/tests/run_acceptance.py
```

Pure/injected-failure tests and packaging alone:

```bash
node --test caldav_assistant_thunderbird/tests/*.test.mjs
python caldav_assistant_thunderbird/tools/package.py
```

Evidence is in `artifacts/real-thunderbird-result.json`,
`artifacts/real-wordpress-result.json` and `artifacts/*-readback.ics`.
The Thunderbird receipt contains the SHA-256 of the exact tested XPI.

## Implementation provenance

The only implementation references were Thunderbird source and its tests:
`CalTodo.sys.mjs`, `calICalendar.idl`, `calIRecurrenceInfo.idl`,
`calDateTimeUtils.sys.mjs`, `browser_ext_spaces.js`, Thunderbird's Subprocess
usage and the native Subprocess reader contract. The UTC completion conversion
was verified on a host with a non-UTC timezone. Old metadata was inspected only
for add-on identity and the isolated migration's persisted keys/record shapes.

This is a reviewable candidate on an independent branch. It does not claim
installation or acceptance on the user's actual profile/server, and no existing
user Task/Event data was deleted during testing.
