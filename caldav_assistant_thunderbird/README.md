# caldav_assistant_thunderbird

Canonical Thunderbird add-on for CalDAV Assistant.

## Current canonical version

**0.3.16**

This directory is the canonical Thunderbird source. Do not use the legacy
`integrations/thunderbird/manifest.json` Native Host line to determine the
current add-on version.

## Architecture

Thunderbird owns VTODO/VEVENT objects and its existing Calendar/Tasks provider
connection to CalDAV. CalDAV Assistant does not maintain a second Task lifecycle.

The only persistent Assistant runtime fact is one opaque Task instance id:

```text
caldavAssistant.currentWorkId = <Thunderbird Task instance id> | null
```

User settings are persisted separately. Audit and WordPress records are history,
not runtime state.

The Task controls are exactly:

```text
Start    -> STATUS:IN-PROCESS
Stop     -> STATUS:NEEDS-ACTION
Complete -> STATUS:COMPLETED
Cancel   -> STATUS:CANCELLED
```

There is no Assistant Pause/Resume/Switch Away state, no paused marker, and the
Task lifecycle does not create or manage Work VEVENTs.

## Build

```bash
cd caldav_assistant_thunderbird
chmod +x packaging/build-xpi.sh
packaging/build-xpi.sh dist/caldav-assistant-experimental-0.3.16.xpi
python3 tests/check-xpi.py dist/caldav-assistant-experimental-0.3.16.xpi
```

## 0.3.16 result

- old 0.3.15 runtime objects migrate once to one `currentWorkId`;
- Start/Stop/Complete/Cancel write standard Thunderbird VTODO STATUS values and
  read them back;
- a stale current id is reconciled against Thunderbird and cleared;
- completing or cancelling a non-current Task is allowed;
- generic VEVENT support remains a Thunderbird Calendar capability but is no
  longer part of Task runtime state.

## Release gate

A release is not complete merely because the XPI builds. CI must cover syntax and
behavior harnesses, XPI contract checks, real Thunderbird + Radicale acceptance,
and real Thunderbird + WordPress acceptance. The user performs final secondary
acceptance after those gates pass.
