# CalDAV Assistant Experimental

Current build: **0.3.12** for official Thunderbird **153.0.2 through 153.1.x**.

0.3.15 keeps the segmented Work flow and makes Task switching restore the previous Task to exactly the state it had before Start. The Work page shows only the current Task. Task browsing and selection live on a separate Task picker page. Switching remains deliberately two-step: release the current Task, then explicitly start the selected Task. The add-on remains a direct Thunderbird Calendar/Tasks provider client.

## 0.3.12 logging and WordPress changes

- WordPress has a first-class page in the main navigation, with visible settings, daily-work-log state and Outbox state.
- WordPress quick/full tests show the underlying REST attempt, conservative retry, WP-CLI fallback, timing and errors instead of only the final success summary.
- Operation audit is stored under per-local-date keys and can be copied per day, as currently visible text, or as JSON.
- Technical diagnostics are physically split into per-local-date files; the previous combined log is migrated on first use.
- Closing a Work VEVENT writes one idempotent time-range entry into the matching daily WordPress post and read-backs the marker to verify the write.
- WordPress failure queues an Outbox item and never rolls back the CalDAV Task action. Startup and the WordPress page can retry the Outbox.
- Work sessions that cross local midnight are split into the corresponding daily posts.

## Work flow

The Work page is intentionally small. It shows only the current Task, elapsed time and direct controls:

- Working Task: Pause / Complete / Cancel / Switch Task.
- Paused Task: Resume / Complete / Cancel / Switch Task.
- No current Task: Select Task.

Task browsing is a separate page. The Task picker owns the Incomplete/Today/Overdue/Completed/All filter, Calendar filter and search field.

Starting and switching are kept explicit:

```text
Select Task
-> Start this Task
-> Work

Switch Task
-> select target
-> Put current Task aside
-> target selection stays in place
-> Start this Task
-> Work
```

Switching away is not Pause and is not Complete. The current open Work VEVENT is closed and verified, then the VTODO is restored to the exact status / paused marker / percent-complete snapshot captured immediately before Start. For an ordinary incomplete Task this means it returns to incomplete (`NEEDS-ACTION`), with no Assistant paused marker and no Resume state. The runtime current-task pointer is then released. The target Task is not auto-started.

The Work page does **not** contain the Task browser, filter controls, detailed operation logs, UID, raw VTODO state, internal Assistant state, Work Calendar selectors, provider IDs, or JSON details.

## Five pages

- **Work** — Task lifecycle.
- **Today** — today's workflow activity.
- **Record** — append one log entry (and optional attachments) to today's WordPress log post.
- **Logs** — complete persistent audit + technical diagnostics.
- **Tools** — settings and read/write connection tests.

## Guided defaults

Tools owns two lightweight user preferences:

- Default Task view (Incomplete by default).
- Default Task Calendar (including All Calendars).

When more than one Task Calendar exists and no default has been chosen, Work shows a short link to the exact Tools section. If a saved Calendar later disappears, Work falls back to All Calendars for the current session and guides the user back to settings instead of silently replacing the preference.

Saving Calendar/view defaults creates a one-step settings undo snapshot. The user can immediately undo the choice from Tools.

Inferred Work Calendar choices are one-shot only; the Assistant no longer silently persists an inferred Calendar as a user preference.

## Simple internals

The core is plain functions plus a few plain JavaScript objects. There is no extra workflow framework or class hierarchy.

`core/executor.js` exposes Start/Pause/SwitchAway/Resume/Complete/Cancel functions; `putAside` remains only as a compatibility alias for older 0.3.11–0.3.14 callers.

`core/connection.js` tests Calendar reads/writes.

`core/wordpress.js` talks to WordPress.

`core/storage.js` stores settings/runtime/audit and enforces the log-before-display rule.

## Reliability rules

Data-changing Calendar paths use:

write -> read back -> compare -> Result

A Result is persisted to the audit log before it is returned to the UI. If logging itself fails, the visible Result says so.

Start/Resume create Work VEVENTs. Pause/Complete/Cancel close them.

Task/Event facts remain in Thunderbird/CalDAV.

## Connection tests

Calendar full test creates only a temporary VEVENT:

create -> read -> update -> read -> delete -> verify absence

It never creates a VTODO.

WordPress full test uses a temporary Draft post + test media, verifies them, then deletes them.

Normal Record writes are different: each submission appends one Gutenberg log entry to the single published daily post (new posts keep the existing helper title shape, for example `October 1  Thursday  2026`). The daily post is created only when that day's post does not yet exist; Record never asks the user for a per-entry post title or post status. Text entries keep the existing local `HH:MM` prefix, and attachments are appended as native Gutenberg media/file blocks.

## Diagnostics

The Logs page contains both:

- operation/audit records;
- the extension-owned profile log `caldav-assistant-experimental.log`.

See `DIAGNOSTICS.md`.

## Testing

Release acceptance requires more than syntax/unit tests. See `TESTING.md` and `NOTE.md`.
