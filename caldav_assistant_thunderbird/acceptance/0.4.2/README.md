# 0.4.2 release evidence and source provenance

The accepted runtime source is commit `5ae563e24868e1454fcc6ca564ad78e707afbdaf` on `integrate/wordpress-verified-release`. It was recovered intact with a clean worktree. No runtime source changes were made during release closure.

- Build ID: `20261005T090627Z-bb8c684b828b46b3a4cdba3bdd62a91e`
- SHA-256: `254314340f4cd4b33f4c60eba5b4d041b27ff36a2db358dc71f5a0eb688c46d4`
- Source digest: `dc987aa9ee9b4160ec2a3740693247c946bc5eb1c11e798a374b13eca31bda03`
- Version: `0.4.2`
- Install ID: `ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net`
- Compatibility: Thunderbird `153.0.2` through `153.1.*`; exact-package real acceptance used `153.1.0 ESR`.
- Unmodified accepted XPI: [release package](../../releases/0.4.2/caldav-assistant-thunderbird-0.4.2-20261005T090627Z-bb8c684b828b46b3a4cdba3bdd62a91e.xpi)

Package entries were compared byte for byte with recovered addon sources; the digest and archive hash match. The original `build-info.json` remains inside the XPI. The source commit refers to acceptance time; publication-only documentation and CI changes do not change runtime bytes.

## Preserved evidence

The original hash-specific acceptance document is historical and retains its then-current “not pushed / not merged” statement. Publication progress is separate from that evidence.

- `caldav-offline-output/report.json`: all 30 real Thunderbird/Radicale checks pass with the exact archive SHA; includes authoritative VTODO server readbacks and receipts.
- `wordpress/report.json`: real WP-CLI and REST, self-signed TLS, post/media cleanup, manual logging, ambiguity, restart, outage/recovery, idempotency and original date all pass.
- `wordpress/native-task-output/report.json`: native Task actions produce five closed sessions, acknowledged through independent WordPress output.
- Screenshots, original regression log and service logs are preserved alongside reports. All services are isolated test fixtures, not the user's site.

## Release closure

The interrupted work left no uncommitted source changes. The stale 0.3.16 README was updated and evidence was checked into the release tree. CI was corrected to run the current full harness, pass the real driver's named arguments and test the unchanged release XPI. WordPress CI now prepares a disposable fixture for the already accepted integrated driver rather than instrumenting a different addon copy.

The original accepted commits were uploaded intact and protected as GitHub branch `recovery/accepted-thunderbird-0.4.2`. The publication branch includes accepted commit `5ae563e24868e1454fcc6ca564ad78e707afbdaf` as an ancestor. `accepted-source.bundle` also preserves the original three commits, based on `fc59b2aab246e689a302e0a153e6ecaec77c2f37`. An isolated checkout of the exact accepted commit reproduced the original Build ID with byte-identical XPI output and the same SHA-256. To recover the accepted history from the bundle after cloning:

```bash
git bundle verify caldav_assistant_thunderbird/acceptance/0.4.2/accepted-source.bundle
git fetch caldav_assistant_thunderbird/acceptance/0.4.2/accepted-source.bundle refs/heads/recovery/accepted-thunderbird-0.4.2:refs/heads/recovery/accepted-thunderbird-0.4.2
```

Runtime byte equality permits reuse of the saved exact-package acceptance. CI/fixture changes require their own checks; they do not expand Thunderbird compatibility or alter product direction.
