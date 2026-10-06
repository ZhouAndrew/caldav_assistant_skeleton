# Independent Post preview — 0.4.4 acceptance

Implementation: `11984110ddd851693cf8b0d4f74fb9f3749b3a41` on `feat/work-quick-capture`.
Accepted unchanged XPI: `caldav-assistant-thunderbird-0.4.4-20261006T035855Z-cf56d4f5623e4ec39f5cee6947040cd3.xpi`.
SHA-256: `f2f0044e7029550336e4de0e474d58984e7fba0b1247b038fb6865bf2aa16b55`.

0.4.3 incorrectly initialized the preview only after a successful append.
0.4.4 gives the preview its own controller, initialization and refresh button.
`post-preview.js` directly calls the read-only `AssistantWordPress.readDailyLogPost()`
on page open. That API uses the original daily lookup/selection with creation disabled.
Missing Post means a visible empty message, without Post creation or append.
The Open Post link belongs to the preview card. Quick Capture never reads or
controls the iframe, its link or preview status; successful append only emits a
refresh notification. Normal same-origin scrolling and the already verified,
scoped cross-origin scrolling boundary are retained.

## Real acceptance

Isolated real Thunderbird 153.1.0, WordPress 7.1.2/MariaDB via existing WP-CLI,
Radicale for Work regression and native OS clipboard/XTEST/GTK inputs.
This is isolated environment acceptance, not a claim about the user's LAN.

The exact final XPI was installed unchanged in both test profiles.
`report.json` records all 11 passing checks, including:

- Opening with no today Post creates nothing and leaves Outbox empty.
- Opening/reloading shows an existing full Post without any capture.
- Removing the entire Quick Capture card still permits direct Post read/refresh.
- Text, real screenshot and native clipboard-file paste work.
- Native single/multiple-file drops append and upload.
- Each successful append has a new loaded Post URL, all full-page resources,
  existing content, a verified receipt and measured bottom scroll position.
- Native iframe drop causes no upload or append.
- Real connection refusal retains Outbox and leaves currentWorkId unchanged.

`work-regression.json` records 30 passing real Thunderbird/Radicale checks,
including Start/Stop/Complete/Cancel, recurring identity, restart, server read-back,
WordPress failure isolation, native toolbar and extension lifecycle cleanup.
`npm test`, read-only missing/ambiguous/selected target assertions, strict typing,
scoped input/standalone preview harnesses, packaging and frozen XPI checks passed.

Reproduction uses the existing private fixture runtime and:

```sh
npm test
python3 tests/real-quick-capture.py --runtime "$FIXTURE_RUNTIME" --xpi "$XPI" --output "$CAPTURE_OUTPUT"
python3 tests/real-acceptance.py --thunderbird "$THUNDERBIRD" --xvfb "$XVFB" --xpi "$XPI" --output "$WORK_OUTPUT"
```

Work actions, currentWorkId, Task/Event state and CalDAV writing were unchanged.
The existing append path retains its creation, transport, Outbox and verification
semantics. Only the read-only entry and independent preview input boundary were added.
