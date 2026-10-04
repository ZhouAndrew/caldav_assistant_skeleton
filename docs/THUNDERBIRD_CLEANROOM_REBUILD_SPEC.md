# Thunderbird Clean-room Rebuild — Frozen Project Requirements

> **Status: FROZEN / project-wide**
>
> Date: 2026-10-04
>
> This document records the latest accepted requirements for every **new Thunderbird rebuild line**. It supersedes older Thunderbird-specific workflow/runtime requirements where they conflict. It does **not** silently change the generic CLI/Public Python API v1 contract outside the Thunderbird integration.

## 1. Product scope

The new CalDAV Assistant plugin **runs inside Thunderbird**.

Normal operation is:

```text
Thunderbird Add-on / XPI
        ↓
Thunderbird Calendar / Tasks APIs
        ↓
Thunderbird's existing CalDAV connection
        ↓
CalDAV / Radicale
```

The new plugin must not recreate the normal workflow as:

```text
XPI → Native Host → Python Assistant → second CalDAV client
```

A helper process may only exist when a narrowly scoped platform capability truly requires it. It must never become a second workflow authority or second Task state system.

Thunderbird/CalDAV owns Task/Event facts. Existing VTODO/VEVENT data remains authoritative.

## 2. From-zero / clean-room rebuild

Every new rebuild line is a **FROM-ZERO / CLEAN-ROOM** implementation.

Stable 0.3.16 / `main` is only:

- behavior/data compatibility reference;
- stable fallback;
- source of public product constraints;
- a real-world acceptance comparison target.

It is **not** the implementation template for a new rebuild.

Do not incrementally reshape the old plugin into the new architecture. Do not copy old internal implementation code. Do not copy another active rebuild line.

New rebuilds must live in their own isolated implementation directory and branch.

## 3. Parallel construction is mandatory

Multiple ChatGPT/Codex lines may work simultaneously.

Each line is independent:

- independent branch;
- independent implementation directory;
- independent commits;
- independent tests;
- independent XPI;
- independent acceptance evidence;
- independent merge/release decision.

Do not automatically:

- cherry-pick another active line;
- merge another active line;
- rebase one line onto another active line;
- copy implementation code from another line;
- resolve parallel design differences by silently unifying them;
- treat another line's passing tests as evidence for this line.

Shared stable `main` is the common baseline. Parallel branches are experiments, not upstream/downstream relationships.

## 4. Simplified Thunderbird runtime

The old Assistant runtime framework is removed from new Thunderbird rebuilds.

### 4.1 Only four workflow actions

The Thunderbird workflow is:

- **Start**
- **Stop**
- **Complete**
- **Cancel**

Do not reintroduce new workflow actions named or equivalent to:

- Pause
- Resume
- Switch Away

Do not rebuild a second runtime state machine under different names.

### 4.2 Sole current-work pointer

The only Assistant-owned persistent current-work pointer is:

```text
currentWorkId: WorkTaskId | null
```

`WorkTaskId` must preserve recurring occurrence identity, including calendar identity, VTODO UID, and recurrence identity when applicable.

Do not create parallel persistent truth such as:

- runtime.currentTask
- activeTask
- pausedTask
- selectedWork
- workingState
- page-local inferred workflow state

Transient UI selection is not persistent workflow truth.

### 4.3 VTODO is workflow fact

Task status/progress comes from the VTODO.

The new plugin does not own a second Task database.

Start/Stop/Complete/Cancel decisions must be based on authoritative VTODO data plus `currentWorkId`.

### 4.4 Work-session history belongs in DESCRIPTION

New work-session start/end history is recorded in the VTODO `DESCRIPTION`.

Requirements:

- preserve the user's original DESCRIPTION text;
- append Assistant-owned session records without destroying original text;
- record session start;
- record session end/result;
- preserve the pre-Start `STATUS` and `PERCENT-COMPLETE` needed for Stop;
- parsing must be deterministic and safely reject malformed/ambiguous Assistant-owned records before destructive mutation.

New rebuilds do **not** create Work VEVENTs for workflow state/history.

### 4.5 Action semantics

**Start**

- requires a valid, unambiguous VTODO occurrence;
- records a session start in DESCRIPTION;
- records the pre-Start STATUS/PERCENT-COMPLETE required for Stop;
- writes the VTODO;
- performs authoritative read-back and validation;
- only then publishes `currentWorkId`.

**Stop**

- only applies to the current work item;
- closes the active DESCRIPTION session;
- restores the pre-Start STATUS/PERCENT-COMPLETE;
- writes and authoritatively reads back the VTODO;
- validates the result;
- only then clears `currentWorkId`.

**Complete**

- closes any active session with a Complete result;
- writes the normal completed VTODO state;
- validates authoritative read-back;
- clears `currentWorkId` only after the committed Task state is verified.

**Cancel**

- closes any active session with a Cancel result;
- writes the normal cancelled VTODO state;
- validates authoritative read-back;
- clears `currentWorkId` only after the committed Task state is verified.

If an action is not valid for the current item, reject it rather than infer/guess.

## 5. Minimal page contracts

Pages are thin views/controllers, not workflow authorities.

### Task Picker

Input:

- settings;
- native Thunderbird Task query/list/filter.

Output:

- `taskId` only.

It does not pass a runtime object or page-owned business state.

### Task Work page

Input:

- `taskId` only.

It reads the VTODO and `currentWorkId` through application ports/services and exposes only:

- Start
- Stop
- Complete
- Cancel

### Today

Today is a read-oriented projection of authoritative Task/Event data. It does not maintain its own workflow state.

### Logs

Logs/history pages are primarily read-only projections. They do not decide Task truth.

Pages communicate by stable IDs, not by duplicating domain state.

## 6. WordPress

WordPress is independent long-term logging.

It is never Task/workflow truth.

When WordPress logging is enabled, it must be reliable:

- durable Outbox;
- visible/retryable failure;
- duplicate-safe retry behavior;
- WordPress failure must not roll back a successfully committed CalDAV Task action.

Existing WordPress Application Password credentials must migrate exactly and must never appear in diagnostics, logs, CI output, exceptions, snapshots, artifacts, or commits.

## 7. One-time migration only

Legacy runtime compatibility belongs in an isolated, one-time migration boundary.

Migration must be:

- versioned;
- idempotent;
- deterministic;
- testable;
- failure-safe;
- read old data;
- derive the new DESCRIPTION/currentWorkId representation;
- write it;
- authoritative read-back;
- verify;
- only then mark migration complete/remove obsolete runtime data.

Do not leave permanent compatibility branches throughout the new workflow core.

Do not guess on ambiguous legacy state.

## 8. Functional programming / code standard

The required architecture is:

```text
Pure Functional Domain/Core
          ↓
Application actions / explicit plans
          ↓
Ports / Interfaces
          ↓
Imperative adapters
          ↓
Thunderbird / CalDAV / Storage / WordPress / UI
```

### 8.1 Pure core

Start/Stop/Complete/Cancel decision logic must be pure or as close to pure as practical.

The core must not directly:

- call Thunderbird APIs;
- perform HTTP;
- execute WP-CLI;
- read/write browser storage;
- touch DOM;
- get system time implicitly;
- generate random IDs implicitly;
- log to console.

Time, IDs, repositories, storage and external services are explicit inputs/dependencies.

### 8.2 Immutable typed domain

Use strict TypeScript.

Domain values should be `readonly` / immutable where practical.

Use explicit domain types such as:

- TaskIdentity / WorkTaskId;
- RecurrenceIdentity;
- CurrentWork;
- WorkSession;
- ActionResult;
- explicit effect/change plans.

Do not use broad `any` to suppress design problems.

`@ts-ignore`, unsafe casts, or equivalent escapes require a narrow external-boundary reason and explanation.

### 8.3 Functional Core / Imperative Shell

The core computes decisions/plans.

The shell executes side effects.

A typical mutation is:

```text
read authoritative state
→ pure decision/plan
→ adapter write
→ authoritative read-back
→ pure validation
→ publish auxiliary state
```

Do not mix workflow branching, Thunderbird IO, storage writes, WordPress calls and DOM rendering in one function.

### 8.4 Explicit dependencies

No hidden global business-service singletons.

Core dependencies such as clock/repository/storage/logger/WordPress are passed explicitly through ports/application composition.

### 8.5 No duplicated business logic

Today, Work, Task Picker, background code and tests must not each implement their own Start/Stop/Complete/Cancel rules.

UI invokes application actions and renders results.

### 8.6 Single responsibility

Prefer small modules with clear responsibilities.

Avoid giant `assistant.ts`, `background.ts`, `utils.ts` files that become hidden frameworks.

A clean structure may use responsibilities such as:

```text
domain/
application/
ports/
adapters/
ui/
migration/
tests/
```

Exact filenames are not frozen; responsibility boundaries are.

### 8.7 Structured errors

Use stable error categories rather than ad-hoc string matching, including concepts such as:

- NotFound
- Ambiguous
- Conflict
- Unavailable
- Validation
- Permission
- Migration
- ExternalService

UI translates structured errors into user-facing messages.

### 8.8 Dependency discipline

Prefer Thunderbird/WebExtension-native capabilities and small mature dependencies.

Do not introduce Electron, Chromium runtimes, large resident frameworks, or unnecessary state-management systems.

The core must remain usable on low-resource machines.

## 9. Mutation safety

Important mutations follow:

```text
prepare
→ authoritative read
→ plan
→ write
→ authoritative read-back
→ validate
→ publish currentWorkId / auxiliary state
```

Never publish `currentWorkId` before Task mutation verification.

If read-back does not match the intended result, do not report success.

Restart recovery must refuse to guess when:

- scans are partial;
- multiple candidates conflict;
- recurring identity is incomplete;
- migrated state is ambiguous.

## 10. Actual testing is mandatory

Mock/unit tests alone are not acceptance.

Every independent rebuild line must pass four levels.

### A. Pure/core tests

At minimum:

- strict TypeScript typecheck;
- Start;
- Stop;
- Complete;
- Cancel;
- second-Start guards;
- non-current action guards;
- currentWorkId;
- recurring occurrence identity;
- malformed DESCRIPTION/session refusal;
- conflict behavior;
- partial-scan recovery refusal;
- migration;
- secret redaction.

### B. Real service integration

Use **real Radicale**, not only a mocked repository.

Verify create/read/update/read-back and relevant VTODO workflow behavior, recurring VTODO/RECURRENCE-ID, restart and conflict cases.

Use **real WordPress** for supported transports.

Verify authentication, write/read-back, failure, durable Outbox, retry and duplicate prevention.

### C. Real Thunderbird/XPI

Build an actual installable XPI and install it in a real Thunderbird.

Verify, at minimum:

- install;
- restart/load;
- native Calendar/Task discovery;
- Task list/filter;
- Today;
- Task Picker;
- Work page;
- settings;
- real VTODO read/write/read-back;
- Start;
- Stop;
- Complete;
- Cancel;
- Task A → Stop → Task B Start;
- recurring occurrence;
- Thunderbird restart recovery;
- ambiguous recovery refusal;
- WordPress logging;
- WordPress failure/recovery;
- credential migration;
- upgrade/uninstall without data loss.

### D. Human-path / interactive acceptance

Real UI interaction is a release gate.

A representative path must actually be performed, for example:

```text
launch Thunderbird
→ open CalDAV Assistant
→ Today
→ choose a real VTODO
→ Start
→ verify authoritative CalDAV data
→ close Thunderbird
→ restart Thunderbird
→ verify current work recovery
→ Stop
→ verify VTODO restoration/read-back
```

Then separately verify Complete, Cancel, Task switching, recurring occurrence, WordPress online/offline/recovery, and migration.

A green CI run does not override a real-environment failure.

## 11. Test evidence

A PASS claim must record enough evidence to reproduce it:

- branch;
- commit SHA;
- Thunderbird version;
- Radicale version/environment;
- WordPress environment;
- XPI version/hash;
- commands/tests executed;
- real interaction path;
- authoritative read-back result;
- failures/logs when applicable.

Do not report only “tested”, “works”, or “all good”.

## 12. Definition of Done

A feature is **DONE** only when applicable layers have all passed:

```text
implementation
+ strict typecheck
+ lint/format
+ deterministic core tests
+ adapter tests
+ real Radicale
+ real WordPress where relevant
+ real Thunderbird/XPI
+ authoritative read-back
+ human-path interactive acceptance
+ data-preservation verification
```

Before that, report it as **IMPLEMENTED** or **TESTING**, not DONE/RELEASED/READY TO MERGE.

Final merge/release remains a separate user decision.

## 13. Relationship to existing frozen project rules

The broader project rules remain in force:

- CalDAV is Task/Event source of truth;
- local storage/SQLite is auxiliary/cache only;
- WordPress is long-term logging;
- platform differences stay behind adapters;
- user-visible simplicity is preferred over framework convenience;
- core paths remain lightweight;
- unrelated CLI/Public Python API v1 contracts are not silently changed by this Thunderbird rebuild.

Where an older Thunderbird-specific document says to preserve Pause/Resume/Switch Away, Work VEVENT workflow state, or the old runtime framework, this 2026-10-04 Thunderbird rebuild specification supersedes that older Thunderbird-specific requirement.
