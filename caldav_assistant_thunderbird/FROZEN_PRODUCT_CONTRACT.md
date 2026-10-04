# CalDAV Assistant Thunderbird Plugin — Frozen Product Contract v1.0

> **Status: FROZEN**
>
> Effective: 2026-10-04
>
> This document freezes the user-facing product boundaries of the canonical
> Thunderbird add-on. Implementation details may change, but development must not
> change these behaviors for technical convenience.

## 1. Product role

The add-on is an Assistant surface inside Thunderbird. It is **not** a second Task
manager.

- Thunderbird/CalDAV owns Task/Event facts.
- CalDAV remains the source of truth for VTODO/VEVENT state.
- The Assistant may keep only auxiliary state such as currentWorkId, settings,
  audit, undo/outbox and caches.
- WordPress owns long-form/daily records, not Task state.

## 2. Primary surfaces

The primary add-on surfaces are:

- **Work** — current Task lifecycle.
- **Today** — today's workflow activity.
- **Record** — append to the daily WordPress record.
- **Logs** — audit and technical diagnostics.
- **WordPress** — WordPress settings/outbox/connection verification.
- **Tools** — Task defaults and Calendar diagnostics.

A Task picker is **not** a primary navigation destination.

## 3. Task selection

Task selection is an interaction step, equivalent to `choose_task()`, not a
standalone Task-management product.

The frozen selection order is:

1. Prefer the Task already selected in Thunderbird's native Tasks UI when there is
   one unambiguous usable selection.
2. Only when needed, open a lightweight fallback picker.
3. The picker may use Thunderbird-native visibility/filter/search capabilities,
   but it must not create or persist an Assistant-owned Task catalog.
4. After a Task is chosen, the user returns to **Work**; the picker is not a
   long-lived workspace.
5. Do not make users re-select a Task that Thunderbird has already selected.

An implementation file such as `task-picker.html` may exist, but it is an
implementation detail and must not appear as a top-level Assistant section.

## 4. Work lifecycle

The new lifecycle actions are exactly:

- **Start**
- **Stop**
- **Complete**
- **Cancel**

Pause, Resume and Switch Away are legacy migration/history concepts only and must
not return as new user actions.

`currentWorkId` is the authoritative Assistant dynamic work pointer. Starting a
different Task is explicit: stop the current Task, keep the target selection, then
start the target. Never auto-start merely because selection changed.

## 5. Reliability

Authoritative mutations use:

`write -> read back -> compare -> receipt`

- A verified VTODO transition is authoritative.
- Work VEVENTs are auxiliary history, not workflow truth.
- WordPress failure must not roll back a verified Task action.
- User-visible success must not be shown before the authoritative write has been
  verified.
- Results are persisted to audit before display where the current implementation
  already guarantees that order.

## 6. UI boundary

The add-on must remain simpler than Thunderbird's native Task UI.

Forbidden drift includes:

- turning the picker into a permanent "Assistant Task Center";
- duplicating a full Task database or Task-state model;
- adding Assistant-only browsing/editing flows merely because they are easier to
  implement than using Thunderbird/CalDAV;
- placing Task selection alongside Work/Today/Record/Logs/WordPress/Tools as an
  equal top-level product section;
- reintroducing Pause/Resume/Switch Away;
- making WordPress or Work VEVENTs authoritative for Task completion.

## 7. Acceptance

A change touching Task selection or workflow must pass both automated contract
checks and a real Thunderbird human path:

`native selection -> Assistant -> Start -> Work -> Stop/Complete/Cancel`

and the fallback path:

`no native selection -> choose Task -> return to Work -> Start`

No release is accepted if the UI requires duplicate Task selection or behaves like
a second Task manager.

## 8. Change policy

This contract is frozen. A future change to these product boundaries requires an
explicit new user decision and a new frozen-contract version. Refactors, library
changes, CSS changes, performance work and compatibility fixes must stay inside
these boundaries.
