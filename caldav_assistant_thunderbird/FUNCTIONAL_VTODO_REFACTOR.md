# Thunderbird 0.3.17 functional VTODO work-log refactor

Status: **architecture contract before implementation**

This document freezes the refactor boundary for the Thunderbird add-on.  It is
deliberately narrower than the global CalDAV Assistant Public Python API: generic
VEVENT support remains a CalDAV capability, but the Thunderbird work workflow no
longer uses Work Session / Work Event VEVENTs.

## 0. Clean-room rule

This rebuild is intentionally clean-room with respect to earlier CalDAV Assistant
Thunderbird code.

Allowed implementation references:

- Thunderbird Desktop source itself;
- Thunderbird's own extension/API tests;
- iCalendar/CalDAV standards where needed.

Forbidden as implementation references:

- existing CalDAV Assistant / TaskFix workflow, storage, executor, page or test code;
- copying old helper functions and renaming them;
- preserving old module boundaries merely for compatibility.

The old add-on tree may be inspected only to understand legacy persisted data for
one-time migration and to prove that the replacement no longer depends on it.  It
must not be used as a code template.

Initial Thunderbird source provenance:

- `calendar/base/src/CalTodo.sys.mjs` — VTODO completion/progress semantics;
- `calendar/base/public/calICalendar.idl` — calendar provider contract;
- `calendar/base/content/widgets/calendar-filter.js` — native Task filter semantics;
- `calendar/providers/caldav/CalDavCalendar.sys.mjs` — CalDAV recurring-item behavior;
- `calendar/base/src/CalRecurrenceInfo.sys.mjs` — occurrence resolution;
- `mail/components/extensions/test/browser/browser_ext_spaces.js` — Spaces API behavior.

## 1. Product invariants

1. Thunderbird/CalDAV VTODO is the Task fact source.
2. A Task's own `DESCRIPTION` stores Assistant work-session start/end history.
3. `caldavAssistant.currentWorkId` is only an opaque local pointer to the Task
   currently being worked on.  It is not a second Task state machine.
4. User workflow is only: **Start / Stop / Complete / Cancel**.
5. WordPress is an independent logging subsystem.  When enabled it must work,
   surface failures, persist an Outbox and retry; WordPress failure never rolls
   back an already verified VTODO transition.
6. Audit/diagnostics are observations.  They never decide Task state, elapsed
   time, restore state or allowed actions.
7. Pages do not own business state.  Query/render functions are read-only.
8. A page receives only the minimum input needed for its job.

## 2. Old runtime framework to remove

The new production path must not contain or call:

- Work Session / Work Event creation, close, reopen or lookup;
- `X-CALDAV-ASSISTANT-WORK-SESSION`;
- `X-CALDAV-ASSISTANT-WORK-OPEN`;
- `X-CALDAV-ASSISTANT-TASK-UID` as workflow linkage;
- Pause / Resume / Switch Away workflow;
- `working / paused / idle` Assistant runtime state machine;
- restoring Stop state from audit history;
- deriving current elapsed work from audit history;
- page-local inference of current work from a filtered Task list;
- `caldavAssistant.runtime` in steady-state runtime.

Generic VEVENT APIs that belong to the wider frozen CalDAV/Event API are not
removed merely because the old Work Event mechanism is removed.

## 3. VTODO DESCRIPTION work-log format

The user's Description text is preserved byte-for-byte except for one Assistant
block at the end.

Example:

```text
复习第三章，整理错题。

[CALDAV-ASSISTANT-WORKLOG v1]
{"sessions":[{"id":"7d2...","start":"2026-10-03T16:47:50+08:00","end":"2026-10-03T17:23:14+08:00","result":"stop","before":{"status":"NEEDS-ACTION","percentComplete":0}}]}
[/CALDAV-ASSISTANT-WORKLOG]
```

Contract:

- exactly one Assistant block may be managed by the add-on;
- content before the block is user text and must round-trip unchanged;
- the JSON payload is versioned;
- session ids are stable and unique;
- an open session has `end:null` and `result:null`;
- closing a session is idempotent;
- parser failure never causes the add-on to overwrite the Description;
- Start records the pre-Start VTODO status and percent in the same VTODO write
  that opens the session;
- Stop restores those values from the open Description session, not from audit;
- Complete closes the session and writes standard COMPLETED/100;
- Cancel closes the session and writes standard CANCELLED.

## 4. Functional core

Pure modules have no `browser.*`, storage, DOM, WordPress, clock or random calls.

Target pure functions:

```text
parseWorkDescription(description)
serializeWorkDescription(parsed)
openSession(parsed, session)
closeSession(parsed, sessionId, end, result)

deriveTaskWorkState(task, currentWorkId)
planTaskAction(intent, task, currentWorkId, now, sessionId)

deriveTaskPickerView(settings, tasks)
deriveTaskPageView(task, currentWorkId, now)
deriveTodayView(tasks, localDate)
wordpressTransportPolicy(config, failure)
```

`planTaskAction()` returns data only:

```js
{
  ok: true,
  taskPatch: { status, percentComplete, description },
  nextCurrentWorkId,
  closedSession
}
```

or a typed rejection.  It never performs I/O.

## 5. Imperative shell

Only the shell may perform side effects:

```text
read VTODO
-> call pure transition
-> write VTODO
-> read back
-> compare parsed Description + standard VTODO fields
-> update currentWorkId
-> emit diagnostic receipt
-> send/queue WordPress log when a session closes
```

### Crash/restart reconciliation

The VTODO Description is durable CalDAV data; `currentWorkId` is a local pointer.

- pointer -> Task with one open Assistant session: valid;
- pointer -> Task with no open session: clear stale pointer;
- no pointer + exactly one Task with an open Assistant session: restore pointer;
- no pointer + multiple open Assistant sessions: do not guess; report recovery
  error and require explicit repair tooling.

This reconciliation is an explicit startup/recovery command, not a hidden side
effect of a query page.

## 6. Page capability contract

| Page | Inputs | Reads | Writes | Must not know |
| --- | --- | --- | --- | --- |
| Task Picker | settings | native Task query/list | none to Task/work state | currentWorkId, workflow history, WordPress |
| Task Page | taskId | that VTODO + currentWorkId | that VTODO + currentWorkId | Task list/filter state, logs UI |
| Today | date | VTODO work-log projections | none | currentWorkId mutation, WordPress |
| Logs | filters | audit/diagnostics | none by default | Task workflow state |
| Settings/Tools | settings/connection config | settings + connection capabilities | settings; explicit TEST data only | workflow state |
| WordPress | WP config + Outbox | WP status/outbox | WP settings; explicit retry/test | currentWorkId, Task workflow |
| Record | record input | WP config | WordPress record only | Task workflow |

Task Picker outputs only an opaque `taskId` to navigate to Task Page.

Task Page's route input is only `taskId`.  It may query `currentWorkId`
internally because that is part of the Task workflow service, not page state.

## 7. Query/command separation

Queries must not mutate:

```text
getTasks
getTask
getSettings
getToday
getLogs
getDiagnostics
getOutbox
```

Commands are explicit:

```text
startTask(taskId)
stopTask(taskId)
completeTask(taskId)
cancelTask(taskId)
saveSettings(patch)
wordpressTest(...)
retryWordPressOutbox()
clearLogs(...)        # explicit destructive maintenance command
clearDiagnostics(...) # explicit destructive maintenance command
```

Rendering never performs a command.

## 8. WordPress reliability boundary

WordPress uses one transport policy for Quick Test, Full Test, manual Record,
automatic closed-session logging and Outbox retry.

- explicit WP-CLI -> WP-CLI only;
- explicit Application Password -> REST only;
- Auto -> deterministic primary/fallback policy;
- Auto may fall back to configured local WP-CLI for REST network failures or
  REST 401/403;
- every fallback is visible in diagnostics;
- successful VTODO transitions remain successful when WordPress is queued.

## 9. One-time migration only

Steady-state code must not retain the old runtime framework.

A separate, versioned one-time migration may read 0.3.16 data to preserve an
already-active Task:

1. read `currentWorkId`;
2. load that VTODO;
3. if it already has an open v1 Description session, finish;
4. otherwise recover the latest Start timestamp/pre-state from old immutable
   receipt data (legacy runtime only as last fallback);
5. write one open v1 Description session and read it back;
6. remove `caldavAssistant.runtime`;
7. mark migration complete.

Old audit records remain historical diagnostics only after migration.  No normal
workflow function may read them.

## 10. Implementation order

1. Freeze this contract; no production behavior changes.
2. Build pure Description/workflow modules and exhaustive state-matrix tests.
3. Build one Task workflow service around VTODO write/read-back + currentWorkId.
4. Add one-time 0.3.16 migration/reconciliation.
5. Convert Task Page to `taskId -> query -> pure view -> explicit command`.
6. Convert Task Picker to selector only.
7. Convert Today to Description-session read-only projection.
8. Decouple WordPress with one transport policy and session payload.
9. Remove Work Event/runtime/audit-derived workflow code and obsolete settings.
10. Replace Calendar full-write acceptance with VTODO DESCRIPTION CRUD/read-back.
11. Run package/static surface checks.
12. Run real Thunderbird + real Radicale + restart + WordPress fault matrix.
13. Only after those gates pass: bump/package/merge/release candidate.

## 11. Required regression matrix

At minimum:

| Condition | Expected |
| --- | --- |
| no current pointer, selected unfinished Task | Start allowed |
| another current pointer exists | Start rejected |
| current Task hidden by picker filter/search | picker behavior unchanged; it only selects IDs |
| current Task page opened | Stop/Complete/Cancel allowed |
| non-current Task page opened while another is current | no Start; explain current-task conflict |
| Start succeeds, process restarts | reconciliation preserves current Task |
| crash after VTODO Start write but before pointer write | open Description session restores pointer |
| crash after Stop VTODO write but before pointer clear | closed Description session clears stale pointer |
| malformed Assistant Description block | no destructive write; visible error |
| user Description contains arbitrary Unicode/newlines | exact user-text round trip |
| Stop | pre-Start status/progress restored from Description |
| Complete | COMPLETED + 100 + closed session |
| Cancel | CANCELLED + closed session |
| Logs/Today opened | zero workflow/storage mutations |
| Auto REST 401/403 + working WP-CLI | WP-CLI fallback |
| explicit REST 401/403 + working WP-CLI | visible REST failure, no fallback |
| WordPress unavailable during Stop/Complete/Cancel | Task commits; Outbox persists |
