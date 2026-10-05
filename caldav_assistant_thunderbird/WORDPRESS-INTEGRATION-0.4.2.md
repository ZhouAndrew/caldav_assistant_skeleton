# WordPress integration 0.4.2

0.4.2 integrates the independently accepted WordPress 0.3.3 behavior into the canonical Thunderbird add-on. It upgrades the existing add-on ID; it does not install a second workflow plugin.

## Integrated behavior

- Enumerate daily-post candidates across REST pages and WP-CLI; reject ambiguity instead of choosing the first post.
- Display IDs, titles and statuses in WordPress settings. An explicit date/post selection is saved with storage read-back, scoped to the configured site, and reused after restart.
- Persist manual text and attachment bytes before attempting any remote write. Preserve existing workflow Outbox records, dates and idempotency markers.
- Compare the entire post content, ID, title and status after writing. Reject conflicting or repeated markers. Preserve existing text and published status.
- Retry an unavailable output after restart. Never silently evict pending records at a queue size limit. Serialize queue writes and remote log sends across add-on pages with Web Locks.
- Persist uploaded attachment metadata before appending. Validate media ownership and reject changing a target that already owns uploaded attachments.
- Bind local self-signed HTTPS authorization to its exact origin. Saving settings is the explicit authorization action. Status refresh does not reset form inputs.
- Run both WP-CLI and REST when the full write-test button is clicked, regardless of the selected transport. Explicit transports never silently fall back.
- Project verified closed VTODO DESCRIPTION sessions into the durable Outbox after successful Task/receipt commit. Send in the independent output path; never wait for network access or roll back a Task because WordPress failed.
- Preserve the verified native Tasks toolbar Start, sole currentWorkId, four work actions and pure functional core. WordPress remains independent of Task truth.

## Permanent packaging requirement

Every new package has a fresh UTC timestamp plus UUID build identifier in its filename and in `build-info.json`. Metadata also records the source commit and source digest. Existing package files are never overwritten. Add-on identity remains stable so upgrades replace the installed add-on.

`CALDAV_REPRODUCE_BUILD_ID` exists only to reproduce identical package bytes in tests. It must never be reused for changed release bytes. SHA-256 identifies the final archive separately.

## Verification

Run `npm test` in this directory. This includes strict TypeScript, typed/core and adapter harnesses, ambiguity/restart/manual Outbox/conflict/full-content checks, concurrent queue retention, XPI integrity and unique-build/reproduction tests.

Real workflow verification uses `tests/real-acceptance.py` with an unmodified XPI, Thunderbird 153.1.0 ESR, Xvfb and real Radicale. It now enables a genuinely unavailable WordPress output to verify successful Task actions remain independent.

`tests/real-wordpress-integrated.py` drives the unmodified installed package through settings, both transports, full post/media tests, Record submissions, four ambiguous retained logs, explicit target selection, real transport outage, process restart/retry, duplicate prevention and historical dates. Its runtime is an isolated WordPress/MariaDB fixture; never point it at a user's site. Final hash-specific acceptance results are kept with the release evidence.

## Installation

Thunderbird → Add-ons and Themes → gear menu → Install Add-on From File → select the uniquely named 0.4.2 XPI. Restart Thunderbird. Existing 0.4.1 settings and workflow state stay under the same add-on identity.

Open WordPress settings, save the local HTTPS authorization if needed, and run the dual transport test. If existing Outbox records have multiple daily candidates, click Retry, choose the intended article, then click Use selected article and retry. The independent `caldav-wordpress-test` add-on is not required for the integrated module.
