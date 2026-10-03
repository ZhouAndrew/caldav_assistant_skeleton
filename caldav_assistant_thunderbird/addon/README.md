# CalDAV Assistant Experimental

Current build: **0.3.16** for official Thunderbird **153.0.2 through 153.1.x**.

0.3.16 removes the second Assistant Task state machine. Thunderbird owns VTODO/VEVENT objects and CalDAV synchronization; the add-on persists only one current-work id plus user settings. Activity/WordPress records remain history, not runtime state.

## Task lifecycle

The user-visible Task controls are intentionally limited to four operations:

```text
Start    -> VTODO STATUS:IN-PROCESS
Stop     -> VTODO STATUS:NEEDS-ACTION
Complete -> VTODO STATUS:COMPLETED
Cancel   -> VTODO STATUS:CANCELLED
```

There is no Pause/Resume/Switch Away/Put Aside lifecycle and no `X-CALDAV-ASSISTANT-PAUSED` field.

The one persistent runtime value is:

```text
caldavAssistant.currentWorkId = <one Thunderbird Task instance id> | null
```

For recurring Tasks this remains one opaque id string: Thunderbird's instance key. Calendar id, recurrence id, event id, elapsed-time state and pre-Start snapshots are not separately persisted.

## Work

The Work page shows only the current Task.

- Current Task: End / Complete / Cancel.
- No current Task: Select Task.

The Task picker uses Thunderbird's native Task filters and Calendar visibility. Starting a second Task requires ending the current Task first. Ending the current Task sets it back to `NEEDS-ACTION`; it does not create a paused state.

Complete and Cancel are ordinary VTODO status operations and do not require a Task to be current.

## Event boundary

Task lifecycle code does **not** create or manage Work VEVENTs.

Thunderbird remains responsible for Event objects. CalDAV Assistant's generic Event API is retained for Calendar features and connection tests. The full Calendar test may create a temporary TEST VEVENT, but no VEVENT participates in Task runtime state.

## Persistence

Assistant runtime/settings:

- `currentWorkId`;
- settings.

Historical/operational records are separate:

- per-day Activity/Audit records;
- last receipt cache;
- WordPress Outbox and long-term WordPress records.

Legacy 0.3.15 `caldavAssistant.runtime` data is migrated once to `currentWorkId` and removed.

## Reliability rules

Task-changing paths use:

```text
write through Thunderbird
-> read back through Thunderbird
-> compare
-> persist audit receipt
```

On each current-Task read, `currentWorkId` is reconciled with Thunderbird. A stale pointer to a missing, completed, cancelled or otherwise non-`IN-PROCESS` Task is cleared.

A WordPress/logging failure never changes Thunderbird Task facts.

## Pages

- **Work** — current Task and End/Complete/Cancel.
- **Task Picker** — Thunderbird-native filtering, selection and Start.
- **Today** — today's Start/Stop/Complete/Cancel history.
- **Record** — explicit WordPress daily-record append.
- **Logs** — persistent audit + technical diagnostics.
- **WordPress** — WordPress settings/tests/outbox.
- **Tools** — Task-view setting and Calendar provider tests.

## Internals

`core/executor.js` exposes only:

- `start(task)`
- `stop(task)`
- `complete(task)`
- `cancel(task)`
- `currentTask()`

`core/storage.js` exposes `get/set/clearCurrentWorkId` instead of a persisted `idle/working/paused` runtime object.

See `ARCHITECTURE.md`, `TESTING.md` and `NOTE.md` for release acceptance.
