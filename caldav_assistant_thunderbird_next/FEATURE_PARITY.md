# Thunderbird clean-room feature parity gate

The clean-room implementation may remove the old runtime architecture, but it
must not remove normal user-facing capabilities.

This list is a release gate, not an implementation reference.

## Required user-facing surfaces

- Task Picker
  - Thunderbird-native Task filters
  - search
  - calendar selection
  - recurring Task identity
  - open selected Task by opaque taskId
- Task Page
  - Start
  - Stop
  - Complete
  - Cancel
  - elapsed time
  - Task title/status/progress/description
  - current-work conflict/recovery visibility
- Today
  - read-only work-session projection from VTODO DESCRIPTION
- Logs
  - read-only diagnostics/audit projection
  - filtering/search
  - explicit maintenance actions only where needed
- Record
  - manual WordPress record/log entry
- Tools
  - Thunderbird Calendar read test
  - VTODO full write/read-back test
  - visible detailed diagnostics
- WordPress
  - settings
  - Application Password REST
  - WP-CLI
  - Auto transport
  - Quick Test
  - Full Write Test
  - automatic work-session logging
  - persistent Outbox and retry
  - visible transport/fallback diagnostics
- Settings
  - existing compatible user settings migrated
  - WordPress username/Application Password preserved
  - language resources: English and Simplified Chinese
  - manual language-switch UI may be implemented after locale resources

## Workflow/runtime invariants

- VTODO is the Task fact source.
- VTODO DESCRIPTION stores work-session start/end history.
- currentWorkId is the only current-task pointer.
- Workflow actions are only Start / Stop / Complete / Cancel.
- Generic Event/VEVENT support in the wider CalDAV product is not removed.
- Thunderbird work workflow creates no Work Event / Work Session VEVENT.
- WordPress failure never rolls back an already verified VTODO transition.
- Logs/audit never decide Task state.
- Task Picker never decides workflow state.
- Query pages do not mutate workflow state.
- All workflow commands are serialized through one command gateway.
- Every VTODO mutation is write -> read-back verify -> pointer publish/clear.

## Release acceptance

A release candidate is not complete until all of the following pass:

1. pure functional-core tests;
2. migration/password preservation tests;
3. Thunderbird native adapter tests;
4. restart/crash-window recovery tests;
5. WordPress REST/WP-CLI/fallback/outbox tests;
6. English/Simplified-Chinese locale parity tests;
7. packaged XPI static surface checks;
8. real Thunderbird + real Radicale acceptance;
9. real Thunderbird browser-chrome UI interaction tests;
10. restart/reopen acceptance;
11. WordPress fault injection;
12. actual XPI install/update from the previous add-on ID.
