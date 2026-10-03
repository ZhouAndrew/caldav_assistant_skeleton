# Thunderbird typed functional refactor

Status: development scaffold. The installed XPI behavior remains 0.3.15 until each
migration step passes the existing behavior, real Thunderbird + Radicale, and
WordPress acceptance gates.

## Goal

Keep the complete user-visible feature set while reducing Assistant-owned mutable
runtime state and hidden behavior.

The target runtime invariant is:

```text
Assistant-owned authoritative work state
    = currentWorkId: WorkTaskId | null
```

Everything else is either:

- a Thunderbird / CalDAV VTODO or VEVENT fact;
- a derived value;
- settings;
- append-only audit/history;
- WordPress outbox/long-form data.

Task status, paused marker, progress, due dates, categories and completion state must
not be duplicated as authoritative Assistant runtime state.

## Identity

A Thunderbird task is not identified safely by VTODO UID alone. The typed core
therefore defines an opaque `WorkTaskId` built from:

```text
calendar id + VTODO UID + recurrence id
```

This preserves recurring-task safety while still allowing one dynamic Assistant
runtime variable.

## Architecture rule

Use a functional core and imperative shell.

Pure/typed core:

- task identity;
- action legality;
- state derivation;
- task transition plans;
- Agenda / Next decisions;
- validation.

Effect boundary:

- Thunderbird Calendar/Tasks API;
- browser.storage.local;
- WordPress;
- notifications;
- diagnostics/audit persistence.

Core functions must receive time/config/state explicitly rather than reading hidden
globals.

## Type rule

New core code is TypeScript with strict checking enabled. Prefer:

- readonly inputs;
- immutable return values;
- discriminated unions;
- branded identifiers instead of interchangeable strings;
- exhaustive switches;
- explicit `null` for absence.

The XPI may continue to ship JavaScript produced by the build. Thunderbird does not
need a TypeScript runtime.

## Feature-preservation rule

This refactor is not allowed to remove:

- Task selection/filtering;
- Start;
- Pause;
- Resume;
- Complete;
- Cancel;
- switching away/restoring the previous incomplete Task state;
- Today;
- Record / WordPress;
- Logs / diagnostics;
- Tools/settings;
- recurring Task safety;
- read-back verification and failure reporting.

If deleting an internal layer makes an existing user path unavailable, that change
is not simplification and must not merge.

## Migration phases

### Phase 0 — typed guardrail

- add strict TypeScript tooling;
- define domain identifiers and immutable task snapshots;
- define `AssistantRuntime = { currentWorkId }`;
- add pure action/state tests;
- keep 0.3.15 runtime behavior unchanged.

### Phase 1 — compatibility runtime boundary

Introduce storage normalization that can read the existing 0.3.15 runtime object
but exposes only `currentWorkId` to new code. Old stored values must remain
recoverable during migration.

### Phase 2 — derive state

Replace persisted `idle/working/paused` with derivation from:

```text
currentWorkId + current VTODO
```

Pause remains a VTODO fact. UI labels become derived values.

### Phase 3 — remove Work VEVENT as workflow state

Start/Pause/Resume/Complete/Cancel must no longer depend on a Work VEVENT for
correctness. If Work-session history remains useful, it becomes append-only
activity/logging data rather than authoritative workflow state.

### Phase 4 — functional action plans

Move action decisions into pure functions that return explicit change/effect plans.
A thin executor performs Thunderbird/CalDAV/storage effects and verifies read-back.

### Phase 5 — delete obsolete compatibility state

Only after migration and real-user-path acceptance:

- remove old runtime state fields;
- remove Work VEVENT workflow coupling;
- update XPI contract checks;
- update architecture documentation;
- bump the add-on version.

## Release gate

Do not call the refactor complete until all of these pass:

1. strict TypeScript typecheck;
2. typed-core deterministic harness;
3. existing JavaScript behavior harnesses;
4. XPI contract validation;
5. real Thunderbird + Radicale acceptance;
6. real Thunderbird + WordPress acceptance;
7. interactive human-path acceptance for Start/Pause/Resume/Complete/Cancel/Switch;
8. restart/recovery acceptance proving current work can be reconstructed from
   `currentWorkId + CalDAV`.
