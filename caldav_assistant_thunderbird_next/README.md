# CalDAV Assistant Thunderbird — clean-room implementation

This directory is a new implementation. It does not import or reuse the previous
CalDAV Assistant / TaskFix add-on code.

Implementation references are limited to Thunderbird Desktop source and standards.

Initial Thunderbird source references:

- `calendar/base/src/CalTodo.sys.mjs`
- `calendar/base/public/calICalendar.idl`
- `calendar/base/content/widgets/calendar-filter.js`
- `calendar/providers/caldav/CalDavCalendar.sys.mjs`
- `calendar/base/src/CalRecurrenceInfo.sys.mjs`
- `mail/components/extensions/test/browser/browser_ext_spaces.js`

The previous add-on may be inspected only for one-time persisted-data migration.
Production modules in this directory must not import from `../caldav_assistant_thunderbird`.
