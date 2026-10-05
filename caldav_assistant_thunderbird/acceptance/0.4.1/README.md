# 0.4.1 final acceptance

Delivered package: caldav-assistant-thunderbird-0.4.1.xpi.
SHA256: `7c957e134612fc3594013d32f2cb1584b62eb6e40165482c76ab112b0b732e01`.
Real Thunderbird 153.1.0 ESR, Radicale 3.8.1, cached CalDAV, isolated profile,
Xvfb display. The exact unchanged deliverable was installed with AddonManager.

Native Tasks toolbar Start is immediately after Mark Completed. Exactly one
entry is injected. Native 0/1/multiple selection and automatic refresh passed
before any Assistant Work page was opened. Queued native clicks followed by
selection changes to B/none/multiple all rejected the old target. Actual Start
used the same canonical executor and compared authentic server data. Native
Tasks-tab visibility was checked; the screenshot shows the real toolbar.

Start/Stop/Complete/Cancel, active currentWorkId guard, latest server Task data,
UID/recurrence identity, same-profile process restart, offline rejection, repeat
activation, removed-button recreation, actual addon disable/re-enable/uninstall
cleanup and independent server VTODO read-back all passed. Test collection
DELETE was independently verified as absent; temporary profile/data were removed.

`npm test` passed the full suite: typecheck, typed pure core, every plugin harness
including native-start-harness, exact XPI contract and reproducible builds.
The 0.4.0 pure core, executor, CalDAV adapter and unrelated CLI are unchanged.
WordPress remains DEFERRED, independent; existing failure-isolation tests pass.
