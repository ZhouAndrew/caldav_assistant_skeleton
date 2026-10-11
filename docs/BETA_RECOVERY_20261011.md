# Beta recovery increment — 2026-10-11

Status: IMPLEMENTED / TESTING; no real Thunderbird acceptance claim.

The executor now writes and reads back recovery evidence before submitting any Task mutation. Lost write acknowledgements, failed verification reads, and pointer publication failures retain that evidence. Startup, Work-page reconciliation, and the next action first authoritatively read the exact Task occurrence and compare the complete expected status, progress and DESCRIPTION. A match permits verified pointer publication and a recovery receipt without repeating the Task write. A mismatch or unavailable provider retains evidence and blocks new writes; it never guesses that a rejected request did not commit.

The evidence is auxiliary, not another current-work pointer. currentWorkId remains the sole pointer. Existing receipt and independent WordPress output paths are preserved. Work-page refreshes no longer overlap.

Validation: npm test passed (strict TypeScript, typed core, adapter/workflow harnesses, unique XPI builds and frozen package contract). Added lost-read-back recovery cases for all four Actions, executor reload recovery, and refusal to overwrite unresolved writes. git diff --check passed. Harness diagnostics include missing mocked XPCOM profile services; tests still pass.

Limits: no Thunderbird executable in this environment; real Thunderbird/Radicale/human-path acceptance remains open. Unmatched pending writes require explicit inspection; automated discard is deliberately not implemented. External terminal session closure, deleted/moved Task recovery, normal no-op outcome classification and cumulative timing remain separate work.
