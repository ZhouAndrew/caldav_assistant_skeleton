# CalDAV Assistant Experimental 0.3.7 — simple program boundary

The design goal is deliberately ordinary: a small UI, a set of plain functions, a few plain objects, strict read-back checks, and persistent logs.

## Work

`workspace.html + workspace.js` only does this:

existing Task -> select -> Start -> Working -> Pause/Resume -> Complete or Cancel

Rules:

- the Work page defaults to the Incomplete view;
- completed/cancelled Tasks remain available through explicit views instead of being deleted;
- the Work page may temporarily switch view/Calendar without changing persistent defaults;
- the Work page never creates a Task;
- before a Task is selected there are no workflow buttons;
- only actions valid for the current state are shown;
- completed/cancelled Tasks show no workflow buttons;
- UID, raw VTODO status, Work Calendar, provider IDs and JSON details do not appear on the Work page;
- the Work page keeps only a short human-readable recent result.

## Plain action functions

`core/executor.js` is intentionally a file of plain functions. It does not define a class hierarchy or workflow framework.

The public operations are:

- `start(task, workCalendarId)`
- `pause(task)`
- `resume(task, workCalendarId)`
- `complete(task)`
- `cancel(task)`

Data-changing paths use:

write -> read back -> compare -> Result

Start/Resume create Work VEVENTs. Pause/Complete/Cancel close the current Work VEVENT. Rollback code exists only where a partial remote write could otherwise leave inconsistent data.

## Small data objects

Runtime data is ordinary JavaScript objects:

- Task view
- Work event reference
- Runtime state
- Result/receipt
- Settings

There is no domain class hierarchy.

## Logging rule

Every user-visible success/failure result is sent to `AssistantStorage.persistResult()` before the function returns it to the UI.

That function attempts:

Result -> append persistent audit -> cache latest Result -> return to UI

If the persistent audit write fails, `logSaved=false` and the UI must say so instead of pretending the result was safely logged.

The Logs page owns full technical detail. The Work page only shows a short result plus a link to Logs.

## Guided defaults and Tools

`tools.html` owns settings and connection tests.

The default Task view and default Task Calendar are ordinary `browser.storage.local` settings. The Calendar value is Thunderbird's existing Calendar id; the add-on does not maintain a second Calendar registry.

Saving those defaults writes one settings undo snapshot. Undo restores the previous Assistant settings object. If a configured Task Calendar disappears, Work temporarily shows All Calendars and links the user back to Tools; it never silently replaces the saved preference.

A missing Work Calendar may be inferred for one workflow action, but that inferred choice is not persisted automatically.


Calendar full test:

temporary TEST VEVENT -> read -> update -> read -> delete -> verify absence

It never creates a VTODO.

WordPress full test:

temporary Draft Post -> read -> update -> read -> temporary media -> read -> delete media -> delete post

## WordPress

`record.html` is an append-only daily log UI. It has no per-entry title or post-status fields.

Normal Record flow:

today's exact daily title -> find published post -> create it only if absent -> upload optional media to that post -> append one Gutenberg log entry -> read back and verify marker

New daily posts use the existing helper title shape, for example `October 1  Thursday  2026`. Lookup remains compatible with older helper-created titles: full or abbreviated month, the day as a numeric token, weekday and year are matched without depending on spacing or token order.

Each text entry is appended as a new Gutenberg paragraph prefixed with local `HH:MM`. Attachments are parented to the same daily post and appended as native Gutenberg blocks: image, video, audio or file/PDF according to MIME type. Multiple Record submissions on the same day reuse the same Post ID.

The visible result reports the daily Post ID / Media ID values; the full request/result record stays in Logs. Completing a Task still does not implicitly create a WordPress post.

## Data ownership

- Thunderbird/CalDAV = Task and Event facts.
- browser.storage.local = small Assistant runtime/settings/audit state only.
- WordPress = explicit long-form records.

## Top-level UI

Exactly five ordinary pages:

Work | Today | Record | Logs | Tools

The internal implementation may have supporting files, but those are not additional user workflows.
