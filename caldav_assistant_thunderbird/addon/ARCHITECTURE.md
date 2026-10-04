# CalDAV Assistant Thunderbird — program boundary

> **FROZEN implementation/framework contract:** `../FROZEN_IMPLEMENTATION_CONTRACT.md`
>
> **FROZEN product contract:** `../FROZEN_PRODUCT_CONTRACT.md`

The canonical add-on is functional and Thunderbird-native.

## Source of truth

- Thunderbird/CalDAV = Task and Event facts.
- `browser.storage.local` = settings, `currentWorkId`, audit/history and Outbox.
- WordPress = explicit long-form/daily records.

There is no second Assistant Task database and no writable Assistant workflow state
machine.

## Task selection

There is no Task Picker.

The user selects a Task in Thunderbird's native Tasks UI. CalDAV Assistant reads
that native selection. If the selection is empty or ambiguous, the Assistant shows
guidance and performs no fallback selection UI.

## Functional architecture

```text
native UI event
-> pure state/workflow function
-> next state + effects
-> thin effect runner
-> Thunderbird/CalDAV/storage/WordPress adapters
-> verified result
-> pure state update
-> render
```

Workflow policy is expressed with pure functions and immutable data. Side effects
exist only at explicit boundaries.

## Work lifecycle

```text
Thunderbird native selection -> Start -> Stop | Complete | Cancel
```

`currentWorkId` is the only Assistant-owned dynamic work pointer and identifies a
Task by Calendar id + VTODO UID + recurrence id.

Pause, Resume and Switch Away are legacy migration/history only.

## Reliability

All authoritative writes use:

```text
write -> read back -> compare -> receipt
```

Work VEVENT is auxiliary history. WordPress and Work VEVENT failures do not become
Task truth.

## Top-level UI

Exactly:

```text
Work | Today | Record | Logs | WordPress | Tools
```
