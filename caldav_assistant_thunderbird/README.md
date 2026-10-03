# caldav_assistant_thunderbird

Canonical Thunderbird add-on for CalDAV Assistant.

## Current canonical version

**0.3.16**

0.3.16 is the reduced-lifecycle release candidate built from PR #98. It keeps
Thunderbird/CalDAV as the Task/Event source of truth and limits Assistant-owned
authoritative dynamic work state to `currentWorkId`.

The previous canonical baseline was 0.3.15, migrated from the formerly separate
`ZhouAndrew/thunderbird-taskfix` development line. The legacy
`integrations/thunderbird/manifest.json` 0.1.x Native Host line is not the current
Thunderbird add-on.

## 0.3.16 workflow

New workflow actions:

```text
Start -> Stop | Complete | Cancel
```

Pause, Resume and Switch Away are no longer exposed as new workflow actions.

Stop restores the immutable pre-Start VTODO status/progress, normalizes any legacy
paused marker off, closes auxiliary Work history when possible, and clears
`currentWorkId`.

Old 0.3.15 runtime/audit data remains readable for migration and historical timing,
but the new workflow never writes the legacy runtime state machine.

## Architecture

The add-on uses Thunderbird-native Calendar/Tasks APIs and Thunderbird's existing
CalDAV provider connection. The legacy Native Host / Python bridge is not the normal
Task interaction path.

Work VEVENT is auxiliary history, not workflow truth. WordPress is long-form/daily
logging, not Task state.

## Build

```bash
cd caldav_assistant_thunderbird
chmod +x packaging/build-xpi.sh
packaging/build-xpi.sh dist/caldav-assistant-experimental-0.3.16.xpi
python3 tests/check-xpi.py dist/caldav-assistant-experimental-0.3.16.xpi
```

## Release gate

A release is not complete merely because the XPI builds. The exact 0.3.16 head must
pass syntax/typed/behavior harnesses, XPI contract checks, real Thunderbird +
Radicale (including same-profile restart), real Thunderbird + WordPress, connection
diagnostics and the interactive Start/Stop/Complete/Cancel human path.
