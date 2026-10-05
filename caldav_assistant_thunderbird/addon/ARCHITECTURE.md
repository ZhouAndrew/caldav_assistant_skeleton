# CalDAV Assistant 0.4.1

Thunderbird 153.0.2–153.1.x. Select a Task in Thunderbird's native Tasks UI and click Start beside
Mark Completed in its native toolbar. Work shows the current Task and provides
Stop, Complete and Cancel. Zero or multiple selected Tasks disable Start. An existing
currentWorkId prevents a second Start. There is no Assistant Task selector.

## Business and effect boundaries

`src/core.ts` is the canonical pure business source. TypeScript generates
`addon/core/action-plan.js`; do not maintain separate handwritten rules.
It validates identity, native selection snapshots, the four actions, session
history and exact read-back comparisons. Inputs include time and unique tokens;
the core does not access the clock, browser APIs, storage, DOM or network.

`core/executor.js` serializes actions in the background, rereads native selection
and the actual Task, rereads currentWorkId, executes the pure plan, performs an
authenticated CalDAV calendar-multiget, compares, verifies pointer persistence,
and records the receipt. The native provider boundary supports cached calendars;
o successful write alone produces a successful workflow receipt.

## Task facts and recovery

Thunderbird/CalDAV owns Task and Event data. currentWorkId is the only active-work
pointer: Calendar id, UID and recurrence id. Start, Stop, Complete and Cancel are
actions. Task status remains the standard VTODO status, never an action name.
The VTODO DESCRIPTION retains user text and append-only session records with
pre-Start status/progress. Stop restores those values; Complete sets COMPLETED
and 100 percent; Cancel sets CANCELLED. No runtime migration or cached Task object
is used. Restart reads the pointer and actual Task/session history.

Work, Today, Record, Logs, WordPress and Tools remain available. WordPress is an
independent output module and is deferred from the 0.4.0 mainline acceptance;
workflow actions do not call it.

## Verification

Run `npm test`, then `bash packaging/build-xpi.sh`. Production ZIPs are
reproducible and exclude documentation, tests and development dependencies.
`tests/real-thunderbird-caldav.sh --thunderbird /path/to/thunderbird --xvfb /path/to/Xvfb
--xpi /absolute/path/to/final.xpi --output /path/to/evidence` installs the exact
unchanged XPI into an isolated profile and drives real native Tasks and Work UI.
It uses isolated Radicale data and checks server VTODOs independently, recurring
identity, selection races, all actions, same-profile process restart and cleanup.
Requires Radicale, vobject and marionette_driver on Python's import path.

## 0.4.1 native Start patch

`content/native-start.js` only binds DOM/window lifecycle to TaskFix events.
The background derives availability with the existing pure core and forwards
Start to the existing serialized executor. No workflow rule is copied into the
toolbar. Identity snapshots are transient render data; the executor rereads the
native selection and real Task before every Start. Mutation observation and
window lifecycle support late/recreated UI, with full disable/uninstall cleanup.
