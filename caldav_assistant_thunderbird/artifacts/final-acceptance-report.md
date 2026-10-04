# Clean-room Thunderbird candidate — final acceptance record

## Protected commits

- `57d5cf4` — clean-room functional VTODO workflow rebuild
- `c5ed193` — refreshed candidate XPI
- `e89d94a` — real native CalDAV acceptance evidence

## Architecture audit

Audited the latest production XPI source on 2026-10-04.

- VTODO reads/listing and writes are confined to Thunderbird's native `cal.manager`, `calICalendar.getItems`, `calendar.getItem`, and `calendar.modifyItem` APIs in `addon/native-calendar.mjs`.
- Recurrence exceptions use Thunderbird's native `recurrenceInfo.modifyException` and `modifyItem`.
- No production CalDAV HTTP client, Radicale HTTP data path, sync engine, second task database, Native Host, Python bridge, daemon, or task-state database was found.
- Direct HTTP CalDAV access occurs only in `tests/real_thunderbird.py` to provision fixtures and independently read back VTODOs.
- UI pages query through the native adapter and services; authoritative task state is not stored in UI state. Refresh re-queries Thunderbird data.
- WordPress delivery is queued after the VTODO read-back commit and cannot block or roll back task commands. WP-CLI uses Thunderbird `Subprocess` with argument arrays and a 15-second watchdog.
- `currentWorkId` is a local pointer; task work history is stored in VTODO `DESCRIPTION`.

## Test matrix

| Area | Result | Evidence |
|---|---|---|
| Pure domain/services/views/migration tests | PASS: 53/53 | `node --test tests/*.test.mjs` |
| XPI packaging | PASS | `python3 tools/package.py` |
| Real Thunderbird 153.1.0 + Radicale + Marionette DOM actions | PASS | `artifacts/real-thunderbird-result.json`, `*-readback.ics`, `thunderbird-last.log` |
| Process restart and VTODO persistence | PASS | `real-thunderbird-result.json` |
| Recurring occurrence isolation | PASS | `real-thunderbird-result.json` |
| One-time migration against native VTODO and extension storage | PASS | `real-thunderbird-result.json` |
| WordPress REST/WP-CLI/Outbox native E2E | PASS | GitHub Actions run `37188903196`, job `WordPress native REST/WP-CLI/Outbox E2E` (`111396729781`): PHP 8.4 + `pdo_sqlite,sqlite3,curl,mbstring`, PDO gate, official WordPress SQLite fixture, real REST/WP-CLI/Outbox/retry/dedup; artifact `actual-wordpress-e2e-evidence` (`11297323502`). |

## Final artifact

- XPI: `artifacts/CalDAV-Assistant-cleanroom-0.4.0-candidate.xpi`
- SHA-256: `29c4336365e7d5356dfde695eae0a9930213ac799b96c950aa6499493214a4dc`
- Real native provider: Thunderbird 153.1.0 + Radicale

## Permanent release and acceptance rules

The architecture red line is:

`packaged XPI -> Thunderbird native Calendar/Task API -> Thunderbird CalDAV provider -> server`.

Thunderbird is the XPI's Task/VTODO data interface. The add-on must not implement a second CalDAV client, sync engine, Task database, Native Host, Python bridge, or daemon. Radicale HTTP is permitted only for independent E2E read-back.

The formal E2E definition is packaged XPI -> real Thunderbird -> real page clicks -> native provider write -> independent Radicale read-back -> Thunderbird restart -> verification. Thunderbird startup, mocks, smoke tests, and injected tests must never be labelled E2E.

The reproducible baseline is final commit `fa4f67639cbbe26ab9f0806b30965805ecab8ec9`, Thunderbird 153.1.0, and `CalDAV-Assistant-cleanroom-0.4.0-candidate.xpi` with SHA-256 `29c4336365e7d5356dfde695eae0a9930213ac799b96c950aa6499493214a4dc`. The tested XPI must be the same artifact intended for release; it must not be rebuilt from different source after acceptance.

WordPress native E2E is now PASS on GitHub Actions. Run `37188903196` executed the unchanged acceptance with `shivammathur/setup-php@v2` PHP 8.4 and `pdo_sqlite,sqlite3,curl,mbstring`; the `new PDO("sqlite::memory:")` gate passed, official WordPress + SQLite was provisioned, and real REST/WP-CLI/Outbox/retry/dedup evidence was uploaded as artifact `11297323502`. The earlier managed-runner `BLOCKED_BY_RUNNER_ENVIRONMENT` result remains historical evidence only and is not counted as this PASS. No Thunderbird architecture change or lower test standard was used.

The repository contains the dedicated GitHub Actions job `actual-wordpress-native-e2e`, and it completed PASS on run `37188903196` at PR head `775e5a989bff3d354f52a394dd814052391727d4`. The job uploads JSON/log evidence as artifact `actual-wordpress-e2e-evidence` (`11297323502`, SHA-256 digest `7b7c5c4a81b5d7657bed2d442e4f71c0e4b0c134645a53384d23ef86e7402189`).

The XPI, acceptance report, patch, and bundle should be preserved as durable GitHub artifacts or release assets before publication. `/tmp/*.bundle` and `/tmp/*.patch` are temporary recovery copies only.

The current release label is **Thunderbird/CalDAV real-use candidate**, not full-stack final stable, until native WordPress E2E passes.

Installation before final release must document the shortest path: Thunderbird Add-ons Manager -> gear -> Install Add-on From File -> candidate XPI. Upgrade installs the same extension ID over the prior candidate. Uninstall removes the add-on; rollback reinstalls the prior XPI. The add-on never creates a second Task data source; Tasks remain in Thunderbird's existing Calendar provider.
