# CalDAV Assistant Experimental

> **Product contract: FROZEN v1.0 (2026-10-04).** See `../FROZEN_PRODUCT_CONTRACT.md`.

Thunderbird-native CalDAV Assistant add-on for official Thunderbird 153.0.2 through
153.1.x.

The current development line is PR #98. The release number is bumped only after the
real Thunderbird/Radicale/WordPress gates pass.

## Work flow

The Work page is intentionally small. It shows only the current Task, elapsed time
and these actions:

- **Stop**
- **Complete**
- **Cancel**

With no current Task it links to **Select Task**.

Task selection is a transient interaction, not a primary Assistant workspace. Prefer
Thunderbird's current native Task selection; only when needed, use the fallback Task
Picker with Thunderbird-native filters, Calendar visibility and search, then return
to Work.

Starting another Task remains explicit:

```text
Select Task
-> Start this Task
-> Work

Choose another Task while one is current
-> Stop current Task
-> target selection stays in place
-> Start this Task
-> Work
```

Stop restores the old Task to its immutable pre-Start status/progress and clears the
Assistant `currentWorkId`. Any legacy paused marker is normalized off. The selected
target is never auto-started.

Pause, Resume and Switch Away are no longer new actions. Legacy 0.3.15 records using
those terms remain readable only for migration/history.

## Six pages

- **Work** — current Task lifecycle.
- **Today** — today's workflow activity.
- **Record** — append to today's WordPress log.
- **Logs** — persistent audit + technical diagnostics.
- **WordPress** — WordPress settings, Outbox and connection verification.
- **Tools** — Task defaults and Calendar connection tests.

## Data ownership

- Thunderbird/CalDAV owns Task/Event facts.
- Assistant owns only `currentWorkId` as dynamic work state plus settings/audit/outbox.
- WordPress owns long-form/daily records.

The legacy `caldavAssistant.runtime` object is read-only migration input and is never
written by the new lifecycle.

## Simple internals

`core/action-plan.js` contains the pure Start/Stop/Complete/Cancel plan.

`core/executor.js` performs Thunderbird/CalDAV/storage effects and read-back
verification.

`core/connection.js` performs standalone Calendar diagnostics. Its full write test
does not load or call `AssistantExecutor`.

`core/storage.js` stores settings/currentWorkId/audit/outbox and reads old runtime
data only for migration.

## Reliability rules

Authoritative paths use:

```text
write -> read back -> compare -> receipt
```

Start optionally opens a Work VEVENT. Stop/Complete/Cancel optionally close it.
Work VEVENT is history, not workflow truth; its failure is logged but does not undo a
verified VTODO/currentWorkId transition.

Every result is persisted to audit before UI display. If logging itself fails, the
visible result says so.

## Connection tests

Calendar full test creates only a temporary VEVENT:

```text
create -> read -> update -> read -> delete -> verify absence
```

It never creates a VTODO.

WordPress full test uses a temporary Draft post + test media, verifies them, then
deletes them.

## Release acceptance

A successful XPI build is not a release. Required gates include typed/unit harnesses,
XPI contract checks, real Thunderbird + Radicale, same-profile restart recovery,
real Thunderbird + WordPress and interactive Start/Stop/Complete/Cancel paths.
