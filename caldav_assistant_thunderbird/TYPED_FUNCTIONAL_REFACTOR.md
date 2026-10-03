# Thunderbird typed functional refactor

Status: active development on PR #98. The release version is not bumped until the
real Thunderbird/Radicale/WordPress gates pass.

## Goal

Keep Thunderbird/CalDAV as the Task/Event source of truth while shrinking
Assistant-owned mutable workflow state to one value:

```text
currentWorkId: WorkTaskId | null
```

`WorkTaskId` is recurring-safe:

```text
calendar id + VTODO UID + recurrence id
```

Settings, append-only audit/history and the WordPress Outbox are allowed local data,
but they are not a second Task state machine.

## Current lifecycle

The user-facing workflow is deliberately reduced to:

```text
Start
Stop
Complete
Cancel
```

Pause, Resume and Switch Away are no longer new workflow actions.

Stop preserves the data-safety property that previously existed in Switch Away:
it reads the immutable pre-Start snapshot, restores the VTODO status/progress, clears
any legacy paused marker, closes auxiliary Work history when possible, and clears
`currentWorkId`.

Old 0.3.15 pause/resume/switch-away audit records and legacy runtime objects remain
readable for migration and historical timing only. New workflow code must not write
those states or expose those actions.

## Ownership

Authoritative facts:

- Thunderbird/CalDAV VTODO: status, progress, dates, categories, completion and any
  legacy extension properties.
- Thunderbird/CalDAV VEVENT: normal Events and optional Work history.
- Assistant: only `currentWorkId` as dynamic work pointer.
- WordPress: long-form/daily records, never Task state.

Work VEVENT is auxiliary history. Failure to create/read/close it is logged but does
not roll back a successfully verified VTODO + `currentWorkId` transition.

## Architecture

Use a functional core and imperative shell.

Pure/typed core:

- recurring-safe identity;
- Start/Stop/Complete/Cancel legality;
- VTODO change plans;
- `currentWorkId` transitions;
- restore-snapshot validation;
- timing derivation from immutable history.

Effect shell:

- Thunderbird Calendar/Tasks API;
- `browser.storage.local`;
- WordPress;
- notifications;
- diagnostics/audit persistence.

New core code is strict TypeScript. Prefer readonly inputs, immutable return values,
discriminated unions, branded identifiers, exhaustive switches and explicit null.

## Compatibility boundary

Legacy 0.3.15 runtime is read-only migration input.

Allowed:

```text
legacy runtime -> currentWorkId
legacy Start snapshot -> Stop restore fallback
legacy pause/resume audit -> historical elapsed-time reconstruction
legacy Work VEVENT ref -> best-effort cleanup
```

Forbidden:

```text
new workflow -> caldavAssistant.runtime
new Pause/Resume/Switch Away action
runtime.state as workflow truth
runtime.currentTask as identity truth
Work VEVENT as workflow truth
```

## Write ordering

Start:

```text
VTODO write
-> VTODO read-back
-> optional Work VEVENT create/read-back
-> publish currentWorkId
-> persist receipt/audit
```

Stop / Complete / Cancel:

```text
optional Work VEVENT close
-> VTODO write
-> VTODO read-back
-> clear currentWorkId
-> WordPress handoff if a Work history segment closed
-> persist receipt/audit
```

Authoritative VTODO/currentWorkId failures remain strict and rollback-capable.
Work-history failures are visible but non-blocking.

## Release gate

Do not merge/release until all pass:

1. strict TypeScript typecheck;
2. typed deterministic harness;
3. JavaScript behavior harnesses;
4. XPI contract validation;
5. real Thunderbird + Radicale;
6. same-profile restart/recovery of an active `currentWorkId`;
7. real Thunderbird + WordPress;
8. interactive Start/Stop/Complete/Cancel human path;
9. Calendar connection full create/read/update/delete test;
10. no loss of existing Task/Event/WordPress data;
11. no writable legacy runtime or reintroduced Pause/Resume/Switch Away path.
