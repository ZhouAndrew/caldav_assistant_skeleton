# Chat → Codex Handoff — CalDAV Assistant Thunderbird

Date: 2026-10-04
Repository: ZhouAndrew/caldav_assistant_skeleton

## 1. Current authoritative baseline

Stable main:
- commit: d701a456a030a099c83eb6ada887ea94feab68a2
- merged PR: #98
- product line: CalDAV Assistant Thunderbird 0.3.16
- release workflow: Start / Stop / Complete / Cancel
- recurring-safe `currentWorkId` is the only Assistant-owned dynamic current-work pointer
- CalDAV/Thunderbird owns Task/Event facts
- Work VEVENT/history is auxiliary, never workflow truth
- legacy 0.3.15 pause/runtime data is read-only migration compatibility
- Calendar full-write diagnostics are independent from Assistant workflow execution

PR #98 passed the existing repository CI and real Thunderbird + Radicale acceptance before merge.

IMPORTANT PRODUCT DECISION:
The user explicitly superseded the earlier Thunderbird requirement to preserve Pause / Resume / Switch Away.
For the Thunderbird integration, do NOT reintroduce a second runtime state machine. Use:
- Start
- Stop
- Complete
- Cancel

Scope this superseding decision to the Thunderbird integration. Do not silently rewrite unrelated CLI/Public API v1 contracts without a new explicit product decision.

## 2. Active development line

PR: #100
Title: WIP: isolated clean-room Thunderbird VTODO refactor
Branch: refactor/thunderbird-cleanroom-vtodo-agent2-20261003
Base: main @ d701a456a030a099c83eb6ada887ea94feab68a2
Current head: 7d8ebf24d86adc2df55fac12f61112389ea9d99e
State: open, Draft, mergeable
Size at this handoff: 91 commits, 59 changed files, +7773 / -0

The branch is intentionally clean-room and isolated from the other concurrent ChatGPT Thunderbird rebuild line.

Current branch contents are intended to remain limited to:
- `caldav_assistant_thunderbird_next/`
- thunderbird-next-cleanroom CI
- functional VTODO refactor contract

Do not import code from `caldav_assistant_thunderbird_rebuild/` or other concurrent implementation lines unless the user explicitly changes this constraint.

## 3. Reliability rules already implemented in PR #100

- VTODO DESCRIPTION carries work-session start/end history.
- `currentWorkId` is the only current pointer.
- Mutations follow: write -> read-back -> pointer publish.
- Restart recovery refuses to guess after partial scans or conflicts.
- Recurring occurrence identity is preserved.
- Existing WordPress Application Password migrates exactly.
- Secrets must never be passed into diagnostics.

Latest visible UI work at head:
- `caldav_assistant_thunderbird_next/addon/pages/today.js` added.

## 4. Current CI state

At head 7d8ebf24:

GREEN existing repository workflows:
- tests
- real-use-smoothness
- real-wordpress-transports
- caldav-assistant-thunderbird-real-caldav
- thunderbird-integration
- caldav-assistant-thunderbird-selftest
- caldav-assistant-thunderbird-real-wordpress

RED new workflow:
- thunderbird-next-cleanroom

Exact first failure:
```
tests/adapters.test.ts(195,14): error TS2554:
Expected 3 arguments, but got 2.
```

The failure occurs during `npm run typecheck` / `tsc --noEmit`.
Because Typecheck fails first, Pure core tests and Reject old implementation imports are skipped.

FIRST NEXT ACTION:
Fix the adapter test call/signature mismatch at tests/adapters.test.ts:195 without weakening types or compatibility contracts, then rerun the complete thunderbird-next-cleanroom workflow.

## 5. Still WIP according to PR #100

Do not mark complete until these are implemented and accepted:
- real Thunderbird adapter acceptance
- pages/UI completion
- WordPress transport + durable Outbox
- one-time active-session migration
- real Radicale acceptance for the new clean-room implementation
- browser-chrome UI tests
- actual installable XPI

Then run real interactive human-path acceptance, not only unit/CI tests.

## 6. Acceptance / safety requirements

The user requires real human-path / interactive acceptance before calling a fix or release complete.

Protect:
- existing Task/Event data
- recurring-task identity
- WordPress data
- existing Application Password exactly
- stable main 0.3.16 as fallback/reference

Do not:
- merge PR #100 while Draft/WIP gates remain
- claim success from unit tests alone
- create a second Task database or second authoritative workflow state
- guess current work on ambiguous/partial recovery
- expose secrets in diagnostics/logs
- silently overwrite the stable implementation
- conflict with the concurrent ChatGPT development branch

## 7. Recommended execution order for Codex

1. Fix current TypeScript typecheck failure.
2. Get `thunderbird-next-cleanroom` fully green.
3. Verify no old implementation imports.
4. Finish real Thunderbird adapter.
5. Finish Today/Work/Tools/settings UI paths.
6. Implement WordPress transport + Outbox and exact credential migration.
7. Implement one-time active-session migration.
8. Run real Radicale acceptance.
9. Run browser-chrome UI tests.
10. Build real XPI.
11. Install in real Thunderbird and perform interactive Start -> Stop / Complete / Cancel, restart/recovery, recurring-task, WordPress, and data-preservation acceptance.
12. Only after all gates pass: update PR #100 from Draft and consider merge/release.

## 8. Architectural baseline still in force

Unless explicitly superseded above:
- CalDAV remains Task/Event source of truth.
- local state is auxiliary/cache only.
- WordPress is long-term logging, not Task truth.
- platform details stay behind adapters.
- keep the core lightweight.
- do not let implementation convenience change user-visible behavior.

This file is a handoff snapshot, not a replacement for the repository's frozen product/API documents or later explicit user decisions.
