# caldav_assistant_thunderbird

Canonical Thunderbird add-on for CalDAV Assistant.

## Current canonical version

**0.3.15**

This source was migrated from the previously separate development line in
`ZhouAndrew/thunderbird-taskfix`, branch
`fix/caldav-assistant-switch-restore-incomplete-0.3.15`, tested head
`81ba6042271e31857c46a50aadeec67bf82267cd`.

This directory is now the canonical source location. Do not use the legacy
`integrations/thunderbird/manifest.json` (0.1.x Native Host line) to determine the
current Thunderbird add-on version.

## Architecture

The add-on uses Thunderbird-native Calendar/Tasks APIs and Thunderbird's existing
CalDAV provider connection. The legacy Native Host / Python bridge is not the normal
Task interaction path.

## Build

```bash
cd caldav_assistant_thunderbird
chmod +x packaging/build-xpi.sh
packaging/build-xpi.sh dist/caldav-assistant-experimental-0.3.15.xpi
python3 tests/check-xpi.py dist/caldav-assistant-experimental-0.3.15.xpi
```

## 0.3.15 result

When switching away from the current Task, the add-on closes the open Work VEVENT and
restores the original Task to the exact pre-Start status / paused marker /
percent-complete snapshot. Switching is not Pause and does not leave the old Task
resumable. The target Task still requires an explicit Start step.

## Release gate

A release is not complete merely because the XPI builds. CI must cover syntax and
behavior harnesses, XPI contract checks, real Thunderbird + Radicale acceptance, and
real Thunderbird + WordPress acceptance.
