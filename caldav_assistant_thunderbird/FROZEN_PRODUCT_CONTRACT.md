# CalDAV Assistant Thunderbird Plugin — Frozen Product Contract v1.1

> **Status: FROZEN**
>
> Effective: 2026-10-04
>
> v1.1 supersedes v1.0. The earlier fallback Task Picker concept is removed.

## 1. Product role

The add-on is an Assistant surface inside Thunderbird. It is **not** a second Task
manager.

- Thunderbird/CalDAV owns Task/Event facts.
- CalDAV remains the source of truth for VTODO/VEVENT state.
- The Assistant may keep only auxiliary state such as currentWorkId, settings,
  audit, undo/outbox and caches.
- WordPress owns long-form/daily records, not Task state.

## 2. Primary surfaces

The primary add-on surfaces are exactly:

- **Work** — current Task lifecycle.
- **Today** — today's workflow activity.
- **Record** — append to the daily WordPress record.
- **Logs** — audit and technical diagnostics.
- **WordPress** — WordPress settings/outbox/connection verification.
- **Tools** — Task defaults and Calendar diagnostics.

There is no Assistant Task browser, Task Picker, Task list, Task search page or
Task-selection page.

## 3. Task selection

Task selection belongs entirely to Thunderbird's native Tasks UI.

Frozen behavior:

1. The user selects exactly one Task in Thunderbird.
2. CalDAV Assistant reads that native selection.
3. If there is one usable Task, the Assistant can Start it.
4. If there is no Task selected, the Assistant tells the user to select one in
   Thunderbird.
5. If multiple Tasks are selected, the Assistant tells the user to reduce the
   native selection to one.
6. The Assistant must never ask the user to select the same Task again.

Forbidden:

- `task-picker.html` or equivalent product UI;
- an Assistant-owned Task list;
- Assistant-side search/filter/calendar browsing for choosing a Task;
- any fallback picker.

## 4. Work lifecycle

The new lifecycle actions are exactly:

- **Start**
- **Stop**
- **Complete**
- **Cancel**

Pause, Resume and Switch Away are legacy migration/history concepts only and must
not return as new user actions.

`currentWorkId` is the authoritative Assistant dynamic work pointer. Changing the
native Thunderbird selection alone must never auto-start another Task.

## 5. Reliability

Authoritative mutations use:

`write -> read back -> compare -> receipt`

- A verified VTODO transition is authoritative.
- Work VEVENTs are auxiliary history, not workflow truth.
- WordPress failure must not roll back a verified Task action.
- User-visible success must not be shown before the authoritative write has been
  verified.
- Results are persisted to audit before normal UI success display.

## 6. UI boundary

The add-on must remain simpler than Thunderbird's native Task UI.

Forbidden drift includes:

- duplicating Task browsing/selection;
- creating a second Task database or Task-state model;
- reintroducing Pause/Resume/Switch Away;
- making WordPress or Work VEVENTs authoritative for Task completion.

## 7. Acceptance

The required human path is:

`Thunderbird native Task selection -> Assistant Work -> Start -> Stop/Complete/Cancel`

There is no fallback selection path.

A release fails acceptance if the user must choose a Task inside CalDAV Assistant.

## 8. Change policy

This contract is frozen. Any future product-boundary change requires an explicit
user decision and a new frozen-contract version.
