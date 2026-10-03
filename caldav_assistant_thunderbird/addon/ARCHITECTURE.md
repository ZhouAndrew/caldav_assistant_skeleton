# CalDAV Assistant Experimental 0.3.16 — minimal Task boundary

The add-on deliberately keeps Task control smaller than Thunderbird itself.

## Ownership

Thunderbird owns the Calendar/Tasks provider objects and CalDAV synchronization:

- VTODO fields and STATUS;
- VEVENT objects;
- recurrence expansion;
- Calendar selection and visibility;
- provider read/write behavior.

CalDAV Assistant does not maintain a second copy of those objects.

The only persistent Assistant runtime fact is:

```text
current_work_id = <one Thunderbird Task instance id> | null
```

Settings are persisted separately. Audit/WordPress records are history, not runtime state.

For recurring tasks, `current_work_id` is still one opaque string: Thunderbird's stable instance key. No status, Calendar id, recurrence id, event id or timer state is persisted beside it.

## Task lifecycle

The user-visible operations are exactly:

```text
Start    -> STATUS:IN-PROCESS
Stop     -> STATUS:NEEDS-ACTION
Complete -> STATUS:COMPLETED
Cancel   -> STATUS:CANCELLED
```

There is no Assistant-defined Pause, Resume, Switch Away, Put Aside or paused marker.

Start persists `current_work_id` and then asks Thunderbird to write `IN-PROCESS`. Stop writes `NEEDS-ACTION` and clears `current_work_id`. Complete and Cancel update the VTODO through Thunderbird and clear `current_work_id` only when that Task is current.

A non-current Task may still be completed or cancelled. Starting a different Task requires stopping the current Task first.

## Event boundary

VEVENT remains a Thunderbird Calendar object. Task lifecycle code does not create, close, reopen or persist a Work VEVENT reference.

The Calendar connection test may create a temporary TEST VEVENT because it is testing Thunderbird's Event provider, not because Task lifecycle depends on VEVENT.

## Reliability

Every Task mutation follows:

```text
Assistant action
-> Thunderbird provider write
-> Thunderbird provider read-back
-> compare expected standard STATUS
-> persistent audit receipt
```

`current_work_id` is reconciled against Thunderbird on read. If it points to a missing Task or a Task that is no longer `IN-PROCESS`, it is cleared.

Legacy 0.3.15 runtime objects are migrated once to the single id and then removed.

## Logging

User actions are transient commands. Their durable history is an Activity/Audit record containing timestamp, action, Task id and result.

WordPress remains a long-term record path. A WordPress or audit failure must not become a second Task state source.

## UI

Work shows only the current Task and the controls valid for it:

- End;
- Complete;
- Cancel.

Task Picker handles browsing, Thunderbird-native filters and Start. If another Task is current, the picker offers End current Task first; it does not invent a switch state.

## Top-level UI

Work | Today | Record | Logs | WordPress | Tools
