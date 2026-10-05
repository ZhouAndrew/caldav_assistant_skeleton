# CalDAV Assistant Thunderbird Plugin — Frozen Implementation & Framework Contract v1.2

> **Status: FROZEN**
>
> Effective: 2026-10-04
>
> Scope: canonical `caldav_assistant_thunderbird` add-on.
>
> v1.2 supersedes v1.0. It removes the Task Picker and freezes the implementation
> style as functional.

## 1. Frozen framework

The canonical framework is:

```text
Thunderbird XPI / Space
  -> Thunderbird-native HTML/CSS/JavaScript
  -> functional UI state transforms
  -> pure domain/workflow functions
  -> explicit effect descriptions / effect runners
  -> thin Thunderbird Experiment API adapters
       -> Thunderbird Calendar/CalDAV provider
  -> thin storage adapter
       -> browser.storage.local
  -> thin WordPress adapter/outbox
```

Frozen framework rules:

- Runs inside Thunderbird as an XPI/Space.
- No Electron, React, Vue or separate desktop runtime in the core path.
- No Native Messaging/native-host dependency for the canonical Task lifecycle.
- Thunderbird/CalDAV is Task/Event truth.
- `browser.storage.local` is auxiliary state only.
- WordPress is long-form/daily-record storage only.
- Top-level product surfaces are exactly:
  `Work | Today | Record | Logs | WordPress | Tools`.
- There is no Task Picker, fallback picker, Assistant Task browser or Assistant
  Task-selection page.

## 2. Functional programming is frozen

The canonical implementation style is **functional throughout**.

Business/domain/workflow/UI-state code must be organized as functions over explicit
inputs and outputs.

Required:

- pure functions for decisions, validation, mapping and state transitions;
- immutable inputs and returned values;
- reducer-style UI state transitions: `state + event -> nextState/effects`;
- explicit data flow;
- explicit effect values or thin effect-running functions at boundaries;
- composition of small functions rather than stateful controller objects.

Forbidden in core/business code:

- classes as workflow/domain architecture;
- mutable domain objects;
- hidden singleton state machines;
- methods whose correctness depends on implicit mutable object state;
- duplicated imperative workflow branches in UI pages.

Unavoidable side effects are allowed only in thin boundary adapters/runners:

- DOM rendering/event hookup;
- Thunderbird `browser.*` / Experiment API calls;
- CalDAV reads/writes;
- `browser.storage.local`;
- WordPress I/O;
- clock/UUID generation.

Those boundaries must not contain workflow policy. They execute effects produced by
functional code.

`async` is allowed for effect execution. Asynchrony does not change the functional
architecture requirement.

## 3. Frozen persistent variables and identifiers

Only compatibility-sensitive persisted/cross-module variables are frozen. Local
temporary variable names are not.

### 3.1 Current work pointer

```text
caldavAssistant.currentWorkId
```

- the only Assistant-owned writable dynamic current-work pointer;
- value: `WorkTaskId | null`;
- `null` means no current work.

`WorkTaskId` v1 identity:

```text
calendarId + VTODO UID/id + recurrenceId
```

Stored encoding:

```text
encode(calendarId)|encode(id)|encode(recurrenceId)
```

### 3.2 Legacy runtime

```text
caldavAssistant.runtime
```

is read-only migration/history input. New lifecycle code must never write it.

### 3.3 Stable storage keys

```text
caldavAssistant.settings
caldavAssistant.settingsUndo
caldavAssistant.auditDates
caldavAssistant.audit.<YYYY-MM-DD>
caldavAssistant.lastReceipt
caldavAssistant.wordpressOutbox
```

`caldavAssistant.audit` is legacy migration input only.

### 3.4 CalDAV extension properties

```text
X-CALDAV-ASSISTANT-TASK-UID
X-CALDAV-ASSISTANT-WORK-SESSION
X-CALDAV-ASSISTANT-WORK-OPEN
```

`X-CALDAV-ASSISTANT-PAUSED` is legacy compatibility only.

## 4. Frozen lifecycle actions

Exactly:

```text
start
stop
complete
cancel
```

Pause, Resume and Switch Away may only be read for legacy migration/history.

## 5. Frozen native-selection rule

Task choice is not implemented by the Assistant.

```text
Thunderbird native selection
-> exactly one Task?
   -> yes: resolve it and operate
   -> no: show guidance; no fallback picker
```

No Assistant Task list/search/filter/picker may be introduced.

## 6. Frozen mutation sequence

Authoritative mutations use:

```text
write -> read back -> compare -> receipt
```

### Start

```text
read exactly one Thunderbird-native selected Task
-> require currentWorkId == null
-> pure planStart(...)
-> write VTODO IN-PROCESS
-> read back and verify
-> best-effort Work VEVENT history
-> write currentWorkId
-> persist receipt/audit
-> render result
```

### Stop

```text
resolve current Task from currentWorkId
-> pure planStop(...)
-> reconstruct immutable pre-Start state
-> restore VTODO
-> read back and verify
-> best-effort close Work VEVENT
-> clear currentWorkId
-> persist receipt/audit
-> render result
```

### Complete

```text
resolve current Task
-> pure planComplete(...)
-> write COMPLETED / 100%
-> read back and verify
-> best-effort close Work VEVENT
-> clear currentWorkId
-> persist receipt/audit
-> render result
```

### Cancel

```text
resolve current Task
-> pure planCancel(...)
-> write CANCELLED
-> read back and verify
-> best-effort close Work VEVENT
-> clear currentWorkId
-> persist receipt/audit
-> render result
```

## 7. Error/history rules

- Failed authoritative VTODO verification is not success.
- Work VEVENT history failure does not roll back a verified VTODO transition.
- WordPress failure does not roll back a verified Task transition.
- Legacy data is migrated/read, not silently destroyed.
- Normal user-visible result follows persisted receipt/audit.

## 8. What may change

Allowed without a new contract version:

- CSS details;
- helper/local variable names;
- pure-function decomposition;
- performance improvements;
- tests;
- Thunderbird compatibility shims;
- backward-compatible receipt/audit fields.

Not allowed without explicit approval:

- changing persistent-variable meanings;
- adding a Task Picker;
- changing the four lifecycle actions;
- abandoning functional architecture;
- moving workflow policy into side-effect adapters;
- changing the source-of-truth model;
- changing the authoritative write/read-back sequence.


## Final v1.2 corrections (2026-10-04)

- Task Picker and fallback picker do not exist; `task-picker.html` and `task-picker.js` are absent.
- Thunderbird native Tasks selection is the only selection source. Start is enabled iff `currentWorkId === null` and exactly one native Task is selected.
- Start re-reads native selection at click time before any VTODO write.
- `currentWorkId` is the sole dynamic workflow pointer; `caldavAssistant.runtime` and legacy-runtime compatibility are not part of the new architecture.
- The only lifecycle actions are Start, Stop, Complete and Cancel.
- The functional core is the single business source of truth; adapters only execute effects.
- VTODO is authoritative; Work VEVENT and WordPress are auxiliary and cannot roll back verified VTODO transitions.
- Every authoritative mutation is write → read back → compare → receipt.
