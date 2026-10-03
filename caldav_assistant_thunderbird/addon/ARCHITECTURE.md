# CalDAV Assistant Thunderbird — program boundary

The design goal is a small Thunderbird-native UI, plain action functions, strict
read-back checks and persistent diagnostics.

## Source of truth

- Thunderbird/CalDAV = Task and Event facts.
- `browser.storage.local` = settings, `currentWorkId`, audit/history and Outbox.
- WordPress = explicit long-form/daily records.

There is no second Assistant Task database and no writable Assistant workflow state
machine.

## Work lifecycle

The user-facing lifecycle is:

```text
Select Task -> Start -> Stop | Complete | Cancel
```

The Work page shows only the current Task. Task browsing/filtering/search remain on
the separate Task Picker page.

`currentWorkId` is the only Assistant-owned dynamic work pointer. It identifies a
Task with Calendar id + VTODO UID + recurrence id.

Pause, Resume and Switch Away are not new workflow actions. Old 0.3.15 data using
those concepts is migration/history input only.

## Plain action functions

`core/executor.js` exposes:

- `start(task, workCalendarId)`
- `stop(task)`
- `complete(task)`
- `cancel(task)`

All authoritative writes use:

```text
write -> read back -> compare -> receipt
```

Start writes the VTODO first, then optionally opens a Work VEVENT, then publishes
`currentWorkId`.

Stop restores the pre-Start VTODO status/progress from immutable Start history,
normalizes any legacy paused marker off, closes optional Work history, and clears
`currentWorkId`.

Complete/Cancel commit their VTODO terminal state and clear `currentWorkId`.

Work VEVENT is auxiliary history. A missing Work Calendar or Work-history failure is
recorded in the receipt but must not make an otherwise verified Task transition fail.

## Legacy migration

`caldavAssistant.runtime` is read-only migration input. New actions never write it.
Old pause/resume/switch-away audit records remain readable so historical timing and
old sessions can be recovered safely.

## Logging

Every user-visible success/failure is sent to
`AssistantStorage.persistResult()` before it is returned to the UI.

```text
Result -> persistent audit -> latest Result cache -> UI
```

If persistent audit fails, the returned result exposes `logSaved=false`.

## Tools / connection tests

Calendar quick test reads Calendars and existing VTODOs.

Calendar full write test is self-contained and does not depend on Workflow Executor:

```text
temporary TEST VEVENT -> read -> update -> read -> delete -> verify absence
```

It never creates a VTODO.

WordPress full test:

```text
temporary Draft -> read -> update -> media -> read -> delete media -> delete post
```

## WordPress

Record appends explicit entries to the daily WordPress post. Closing a Work-history
segment may append an idempotent time-range record. WordPress failure is queued in
the Outbox and never rolls back a committed Task action.

## Top-level UI

Six ordinary pages:

```text
Work | Today | Record | Logs | WordPress | Tools
```

Supporting files are implementation details, not extra workflows.
