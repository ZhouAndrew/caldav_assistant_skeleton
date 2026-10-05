# 0.4.0 final acceptance

The unchanged installed package has SHA256 `42899819626e5464b4c6689cb5078c98f669913b921c3f6ec1a84d1ffa924beb`.
Thunderbird 153.1.0 ESR, Linux, Xvfb TCP display; real Radicale 3.8.1.
The isolated calendar uses Thunderbird's cached CalDAV provider.

All native selection, 0/1/multiple selection, UI refresh, TOCTOU, latest server
Task data, four actions, currentWorkId second-Start guard, recurrence UID and
RECURRENCE-ID, same-profile process restart, offline rejection and test-data
cleanup checks passed. The JSON includes actual installed-plugin receipts and
independent HTTP VTODO read-back comparisons. Start selected in Thunderbird;
there is no development-directory loading or instrumented XPI.

`npm test` passed typechecking, typed pure-core tests, every Thunderbird plugin
harness, XPI contract and two byte-identical production build tests.
`tests/real-thunderbird-caldav.sh` reproduces the real acceptance with an unchanged
XPI. WordPress acceptance is deferred and independent; workflow tests prove its
failure does not affect the four actions.

Additional unchanged Python CLI regression suite: 756 passed, 1 skipped,
8 failed because this cloud execution environment prohibits AF_UNIX socket
creation. The failures are IPC tests in test_extreme_frontend_runtime,
test_production_runtime_process_e2e and test_runtime_ipc_lifecycle_completion.
These CLI tests are outside the Thunderbird XPI runtime and release suite.
