# AGENTS.md

## Project-wide rule for new Thunderbird rebuilds

Before editing any new Thunderbird rebuild line, read:

- `docs/THUNDERBIRD_CLEANROOM_REBUILD_SPEC.md`

That document is **FROZEN** for the current Thunderbird from-zero rebuild effort.

Hard constraints:

- the new plugin runs **inside Thunderbird** and normally uses Thunderbird Calendar/Tasks APIs and Thunderbird's existing CalDAV connection;
- every new rebuild line is **from-zero / clean-room**;
- parallel ChatGPT/Codex lines are **independent** and must not cherry-pick/merge/copy one another unless the user explicitly orders it;
- CalDAV/VTODO is Task truth;
- `currentWorkId` is the only Assistant-owned current-work pointer;
- lifecycle is **Start / Stop / Complete / Cancel**;
- do not rebuild Pause/Resume/Switch Away, Work VEVENT workflow state, or a second runtime state machine;
- work-session history goes in VTODO `DESCRIPTION`, preserving original user text;
- Task Picker outputs `taskId` only; Work page takes `taskId` only; pages do not own business state;
- use a **pure functional core + imperative adapter shell** with strict types, immutable domain values, explicit dependencies, ports/adapters, deterministic tests and no duplicated business rules;
- important writes use **write → authoritative read-back → validate → publish auxiliary state**;
- WordPress is independent long-term logging with durable/retryable failure handling and never workflow truth;
- real Thunderbird + real XPI + real Radicale + real human-path acceptance are required; unit/mock/CI-only success is not release acceptance;
- do not silently change unrelated frozen CLI/Public Python API v1 contracts.

If an older Thunderbird-specific implementation note conflicts with the frozen 2026-10-04 rebuild spec, follow the newer rebuild spec.
