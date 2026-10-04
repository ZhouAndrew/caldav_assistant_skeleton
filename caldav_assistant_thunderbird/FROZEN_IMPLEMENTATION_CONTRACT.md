# CalDAV Assistant Thunderbird Plugin — Frozen Implementation & Framework Contract v1.0

> **Status: FROZEN**
>
> Effective: 2026-10-04
>
> Scope: canonical `caldav_assistant_thunderbird` add-on.
>
> This freezes the compatibility-sensitive variables, implementation sequence and
> framework. Refactors may improve internals only when these contracts remain true.
> Changing them requires an explicit new frozen-contract version.

## 1. Frozen framework

The canonical add-on framework is:

```text
Thunderbird XPI
  -> Thunderbird-native HTML/CSS/JavaScript UI
  -> pure workflow planning (core/action-plan.js)
  -> imperative workflow executor (core/executor.js)
  -> Thunderbird Experiment APIs
       -> Thunderbird Calendar/CalDAV provider
  -> browser.storage.local for Assistant auxiliary state
  -> WordPress adapter/outbox for long-form records
```

These framework decisions are frozen:

- The add-on runs inside Thunderbird as an XPI/Space, not Electron and not a
  separate desktop application.
- The canonical runtime uses Thunderbird-native APIs and Experiment APIs.
- No Native Messaging/native-host layer is required for the canonical Task
  lifecycle.
- UI runtime stays lightweight: ordinary HTML/CSS/JavaScript; no React/Vue/Electron
  framework is required or introduced into the core path.
- Workflow decision logic remains separated from side effects:
  `action-plan.js` is pure and does not call `browser.*`;
  `executor.js` performs Thunderbird/CalDAV/storage/WordPress effects.
- Thunderbird/CalDAV remains the Task/Event source of truth.
- `browser.storage.local` stores Assistant auxiliary state only; it must never
  become a second Task database.
- WordPress remains a separate long-form/daily-record path and must never become
  Task workflow truth.
- The top-level Assistant product surfaces remain:
  `Work | Today | Record | Logs | WordPress | Tools`.
- Task selection is a transient interaction. A fallback picker file may exist, but
  it is not a seventh primary workspace.

## 2. Frozen persistent variables and identifiers

Only compatibility-sensitive persisted/cross-module variables are frozen here.
Local temporary variable names inside a function are **not** frozen.

### 2.1 Authoritative Assistant work pointer

```text
caldavAssistant.currentWorkId
```

- Meaning: the only Assistant-owned writable dynamic pointer to current work.
- Value: `WorkTaskId | null`.
- `null` means there is no current work Task.
- It must not be replaced by a writable workflow state machine.

The v1 `WorkTaskId` identity is the tuple:

```text
calendarId + VTODO UID/id + recurrenceId
```

The stored v1 encoding remains three URL-encoded components joined by `|`:

```text
encode(calendarId)|encode(id)|encode(recurrenceId)
```

A future encoding change requires backward-compatible migration and a new frozen
contract version.

### 2.2 Legacy runtime

```text
caldavAssistant.runtime
```

is frozen as **read-only legacy migration/history input**.

New lifecycle code must never write a new runtime state machine into this key.

### 2.3 Other stable storage keys

The following keys and meanings are compatibility-sensitive:

```text
caldavAssistant.settings
caldavAssistant.settingsUndo
caldavAssistant.auditDates
caldavAssistant.audit.<YYYY-MM-DD>
caldavAssistant.lastReceipt
caldavAssistant.wordpressOutbox
```

`caldavAssistant.audit` is legacy migration input only.

These keys may gain backward-compatible fields, but their existing meaning must not
be silently repurposed.

### 2.4 CalDAV extension properties

The following persisted iCalendar properties are frozen where already used:

```text
X-CALDAV-ASSISTANT-TASK-UID
X-CALDAV-ASSISTANT-WORK-SESSION
X-CALDAV-ASSISTANT-WORK-OPEN
```

`X-CALDAV-ASSISTANT-PAUSED` is legacy compatibility state only. New lifecycle
design must not reintroduce Pause as a primary action.

## 3. Frozen lifecycle action names

The new workflow action set is exactly:

```text
start
stop
complete
cancel
```

User-facing equivalents are Start / Stop / Complete / Cancel.

Pause, Resume and Switch Away may be read for legacy history/migration but may not
return as new writable workflow actions.

## 4. Frozen implementation sequence

Authoritative mutations use:

```text
write -> read back -> compare -> receipt
```

A write is not user-visible success until the authoritative CalDAV object has been
read back and checked.

### Start

Frozen order:

```text
resolve selected Task
-> require currentWorkId == null
-> update VTODO to IN-PROCESS
-> read back and verify VTODO
-> optionally create/read-back Work VEVENT history
-> publish caldavAssistant.currentWorkId
-> persist receipt/audit
-> show result
```

The optional Work VEVENT must not become workflow truth.

### Stop

Frozen behavior:

```text
identify current Task by currentWorkId
-> reconstruct immutable pre-Start Task state from audit/history
-> restore VTODO state
-> read back and verify VTODO
-> best-effort close Work VEVENT history
-> clear currentWorkId
-> persist receipt/audit
-> show result
```

Stop restores the pre-Start Task status/progress; it is not Pause.

### Complete

Frozen behavior:

```text
identify current Task
-> write STATUS:COMPLETED / percent complete
-> read back and verify
-> best-effort close Work VEVENT history
-> clear currentWorkId
-> persist receipt/audit
-> show result
```

### Cancel

Frozen behavior:

```text
identify current Task
-> write STATUS:CANCELLED
-> read back and verify
-> best-effort close Work VEVENT history
-> clear currentWorkId
-> persist receipt/audit
-> show result
```

## 5. Frozen Task-selection implementation boundary

Selection order is frozen:

```text
Thunderbird native selected Task
-> use directly when unambiguous and usable
-> otherwise transient fallback choose_task / Task Picker
-> return to Work
```

The Assistant must not require the user to re-select a Task already selected in
Thunderbird.

The fallback picker may reuse Thunderbird-native filters, Calendar visibility and
search. It must not persist a separate Assistant Task catalog.

## 6. Frozen error and history behavior

- CalDAV/VTODO verification failure means the Task action is not reported as
  successful.
- Work VEVENT history failure is recorded but does not roll back an otherwise
  verified VTODO transition.
- WordPress failure is queued/reported and does not roll back a verified Task
  transition.
- Workflow results are persisted to audit before normal UI success display where
  the current implementation provides this contract.
- Legacy data is migrated/read, not silently destroyed.

## 7. What may still change

Without changing this frozen contract, implementation may change:

- CSS/layout details;
- helper/local variable names;
- internal function decomposition;
- performance optimizations;
- test organization;
- Thunderbird API compatibility shims;
- additional diagnostic fields;
- backward-compatible receipt/audit fields.

It may **not** change the persisted variable meanings, lifecycle action set,
authoritative write sequence, framework boundary, source-of-truth model, or
Task-selection role without a new explicitly approved frozen version.
