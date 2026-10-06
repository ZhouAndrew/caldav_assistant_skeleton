# Work Quick Capture acceptance — 0.4.3

Implementation source: `25f2bd798fe38895710406adf8450b80b5630d9d`.
Branch: `feat/work-quick-capture`.
Baseline: accepted main `b9dcffd6b7d69c5f61f99501e7e2126b33453af2` (0.4.2).

Accepted unchanged XPI:
`caldav-assistant-thunderbird-0.4.3-20261006T030448Z-96b84f88ba0c45749c5aa4d70fa75b77.xpi`.
SHA-256: `eb72514a3af281baacd08c6901fd3a14848ef52eab9d58e405b05a9e370203ec`.
Embedded sourceCommit matches the implementation commit and sourceDirty is false.

Environment: isolated real Thunderbird 153.1.0esr, real WordPress 7.1.2/MariaDB
via the existing WP-CLI transport, real Radicale for Work regression, Xvfb.
This evidence describes the isolated acceptance environment, not the user's LAN.

## Implementation boundary

`quick-capture.js` binds paste/dragover/drop only to `#quick-capture` and calls
`AssistantWordPress.createLog({content, files})`. Existing today selection,
creation policy, authentication, upload, Outbox, append, read-back comparison,
and receipts remain in the original service without changes.

The existing result's `post.link` supplies `post_url` to the UI, the direct
Open Post link and the iframe. A URL search parameter `refresh=Date.now()`
reloads the full WordPress page while preserving other query parameters.
The iframe load handler first attempts normal same-origin scrolling.
Real testing confirmed cross-origin access is denied from moz-extension to HTTP;
the small PostPreview experiment validates the exact Work tab and direct iframe
URL, then a window actor scrolls that document. No server headers, authentication
transport, global drag/paste handlers or workflow code are changed.

## Native input and full Post verification

`tests/real-quick-capture.py` installs the unmodified deliverable and drives:

- OS clipboard + actual Ctrl+V for plain text;
- a real Thunderbird screenshot + native image clipboard + Ctrl+V;
- native XTEST/GTK mouse dragging of real nsIFile objects, one and multiple files;
- native file clipboard + Ctrl+V;
- native dragging onto the iframe, with unchanged Post content and attachment IDs;
- a real refused TCP connection, retained Outbox and unchanged currentWorkId.

After each successful capture, it checks the persisted receipt, authoritative
WordPress content at the last append marker, actual Post URL, fresh iframe URL,
full page text and uploaded resource URLs, and measured scroll position.
`report.json` records all passing checks and real iframe height/scrollY values.
The chrome drag source is test-only fixture UI; the XPI itself is not instrumented.

## Work regression

`tests/real-acceptance.py` runs against the same final XPI with real Thunderbird
and real Radicale. `work-regression.json` records passing native toolbar selection,
Start/Stop/Complete/Cancel, recurring identity, restart recovery, server read-back,
TOCTOU/guards, offline refusal, WordPress failure isolation, reinjection and cleanup.

`npm test` also passed: strict types, typed core, all adapter/workflow harnesses,
scoped Quick Capture harness, XPI frozen-contract and build-identity checks.
`git diff --check` passed. The existing Work controller (workspace.js), Task/Event core and WordPress service
files are byte-identical to the baseline; only the scoped input/preview UI, its new
scroll boundary and package version were changed.

## Reproduction

From `caldav_assistant_thunderbird`, after preparing the private fixture runtime
as described by the existing real WordPress acceptance tooling:

```sh
npm test
bash packaging/build-xpi.sh
python3 tests/real-quick-capture.py --runtime "$FIXTURE_RUNTIME" --xpi "$XPI" --output "$CAPTURE_OUTPUT"
python3 tests/real-acceptance.py --thunderbird "$THUNDERBIRD" --xvfb "$XVFB" --xpi "$XPI" --output "$WORK_OUTPUT"
```

Install/launch tests require a working X server and its xkbcomp, Thunderbird
libraries, marionette_driver and Radicale. The native-drag fixture additionally
uses libX11 and the XTEST extension; these are test dependencies only.
