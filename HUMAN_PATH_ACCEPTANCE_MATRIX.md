# CalDAV Assistant — Human-path Acceptance Matrix

Status: living release gate for v1.x

This document is intentionally stricter than `pytest` coverage. A feature is not
considered release-proven merely because a service or adapter has a passing unit test.
For user-facing behavior, the preferred evidence is the installed
`caldav-assistant` executable following the same input/output path a human follows,
backed by real disposable persistence where practical.

## 1. What counts as real acceptance

A **real** Task/Event acceptance should normally include all of these:

1. install/import the package normally and invoke the installed `caldav-assistant`;
2. use a real disposable Radicale server, not a fake Task/Event adapter;
3. use production Settings/SQLite storage under a disposable user home;
4. allow the real foreground CLI to talk to the real background Assistant through
   the production IPC path;
5. enter choices/commands through the same PromptKit/Menu/REPL path as a person;
6. after every write, read the authoritative VTODO/VEVENT back from CalDAV;
7. verify user-visible progress/errors do not claim success before the authoritative
   write has happened;
8. stop the background process and leave no test state in the real user profile.

For WordPress, a real acceptance uses the production Outbox and transport boundary.
For terminal reminders, a real acceptance observes actual BEL output and actual
Ctrl-C acknowledgement. Platform desktop notification APIs still require a platform
session with a notification daemon and remain a separate manual/platform acceptance.

## 2. Scenario classes

"Every situation" is made finite and reviewable by applying the following classes to
each function where they are meaningful. A cell can be N/A when the situation cannot
occur for that function.

| Code | Situation | Required behavior |
|---|---|---|
| H | Healthy/happy path | correct visible result and correct authoritative data |
| E | Empty/not found | explicit empty/not-found result; no invented data |
| A | Ambiguous | ask only when ambiguity changes the result; preserve identity by UID |
| I | Invalid input | explain and recover/re-prompt where still inside a prompt |
| C | Cancel/back/help | cancel changes nothing; Back returns one level; `?` explains controls |
| U | Unavailable/offline/timeout | no traceback; no false success; safe degraded read or rejected write |
| P | Persistence/restart | state that must persist survives a new process/background restart |
| B | Boundary/time | date-only, timezone, recurrence/window/time-up and other edge semantics |
| X | Cross-platform | Linux plus Windows installed-client path; macOS/manual where needed |
| F | Failure isolation | extension/WordPress/notification secondary failure cannot corrupt Core facts |

Evidence status:

- **REAL** — automated installed-user path with real backing service/state.
- **REAL-PARTIAL** — real path exists but not all applicable scenario classes are yet automated.
- **UNIT/INTEGRATION** — code-level coverage exists but this release gate still wants a human path.
- **MANUAL** — requires a real desktop/OS/hardware environment not supplied by hosted CI.
- **GAP** — no adequate acceptance yet; do not call the feature release-proven.

## 3. Main user interaction matrix

| Function/surface | H | E | A | I | C | U | P | B | X | Evidence / actual interaction |
|---|---|---|---|---|---|---|---|---|---|---|
| Launch interactive CLI | REAL | REAL | N/A | N/A | REAL | REAL | REAL | REAL | Linux REAL; Windows lifecycle REAL | `caldav-assistant` → startup snapshot → `Console ready`; timeout remains in usable console |
| Background auto-start / IPC | REAL | REAL | N/A | N/A | N/A | REAL | REAL | N/A | Linux+Windows REAL | foreground command starts/uses service; `background status`; final `background stop` |
| Guided home menu | REAL | REAL | N/A | REAL | REAL | REAL | N/A | window boundary REAL | Linux REAL | Enter → menu; numeric/exact choice; repeated Enter reuses one coherent snapshot |
| `today` | REAL | REAL | N/A | N/A | N/A | REAL-PARTIAL | N/A | timezone/window covered by integration | Linux+Windows REAL one-shot | read-only; never mutates Task/Event |
| `next` | REAL | REAL | N/A | N/A | N/A | REAL-PARTIAL | N/A | priority/current/Event mix integration | Linux REAL | real Radicale recommendation path in feature demo/conversation |
| `current` / `now` | REAL | REAL | N/A | N/A | N/A | REAL | REAL | paused IN-PROCESS boundary REAL | Linux+Windows REAL | start → current; pause → current must say paused, not active |
| `tasks` | REAL | REAL | N/A | argument error integration | N/A | REAL-PARTIAL | N/A | N/A | Linux+Windows REAL | empty list → `(none)`; populated list stores active numbered references |
| `events` | REAL | REAL | N/A | argument error integration | N/A | REAL-PARTIAL | N/A | internal work Event filtering REAL-PARTIAL | Linux+Windows REAL | user Events only; work-session VEVENT is not exposed as ordinary Event |
| Add Task | REAL | REAL | N/A | REAL date recovery | REAL | unsafe write rejection integration | REAL through CalDAV | REAL `August5`, date-only, future bias | Linux REAL | `add task NAME` → Task timing → Due `August5` → optional fields → Create → reread VTODO |
| Add Event | REAL | REAL | N/A | REAL date recovery via same PromptKit | REAL | unsafe write rejection integration | REAL through CalDAV | REAL all-day `August5`, date-only, future bias | Linux REAL | `add event NAME` → all-day/date-time → Starts → optional fields → Create → reread VEVENT |
| Edit Task due | REAL | E integration | A REAL-PARTIAL | REAL invalid date re-prompt | REAL help/back | write failure integration | REAL CalDAV | REAL future bias/date-only | Linux REAL | `tasks` → `edit 1` → Due → invalid text → same prompt → `August5` |
| Edit Task title | REAL | E integration | A REAL-PARTIAL | empty input PromptKit integration | REAL | write failure integration | REAL | N/A | Linux REAL | numbered reference → Title → new title → old summary absent on server |
| Edit Task priority | REAL | E integration | A REAL-PARTIAL | validation integration | REAL | write failure integration | REAL | 0/9 boundary integration | Linux REAL | numbered reference → Priority → `5` → reread PRIORITY |
| Edit Event title/start/end/location/description/categories | REAL-PARTIAL | E integration | A integration | PromptKit integration | REAL-PARTIAL | write failure integration | REAL | start/date-only REAL; end ordering integration | Linux REAL-PARTIAL | start/date and location exercised against real VEVENT; remaining fields covered at integration level |
| Remove Task | REAL | E integration | A REAL-PARTIAL | syntax integration | REAL cancel | unsafe/offline integration | REAL | active-task delete rejection integration | Linux REAL | cancel → VTODO unchanged; yes → VTODO absent |
| Remove Event | REAL | E integration | A integration | syntax integration | REAL cancel | unsafe/offline integration | REAL | work Event cannot be edited/deleted as ordinary Event integration | Linux REAL | cancel → VEVENT unchanged; yes → VEVENT absent |
| `undo` | REAL | empty-journal integration | N/A | extra-arg integration | N/A | conflict integration | REAL persistent journal | delete restore REAL | Linux REAL | delete Task/Event → `undo` → original object/date fields reread from CalDAV |
| `start` | REAL | REAL no recommendation | REAL task chooser | invalid target integration | confirmation REAL | REAL timeout protection | REAL Activity/Work VEVENT | actual start ≠ planned DTSTART REAL | Linux+Windows REAL | real VTODO IN-PROCESS + real Work VEVENT + Activity Journal |
| Waiting Mode | REAL | N/A | N/A | duration invalid integration | REAL `?`, Ctrl-C decision | reminder feed resilient | work period persisted | REAL countdown/TIME UP | Linux REAL | start/end/remaining; TIME UP does not complete Task |
| `pause` | REAL | REAL nothing-to-pause error | N/A | named argument rejected integration | N/A | secondary hook cleanup isolation integration | REAL | VTODO stays IN-PROCESS, Work VEVENT closes REAL | Linux+Windows REAL | authoritative DTEND/open-marker verification |
| `resume` | REAL | REAL no-paused error | multiple paused chooser integration | arbitrary target rejected integration | chooser cancel integration | secondary hook isolation integration | REAL | opens new work interval REAL | Linux+Windows REAL | paused Activity state → resume → new interval |
| `done` / `complete` | REAL | chooser/none integration | ambiguous Task chooser integration | invalid target integration | chooser cancel integration | WordPress independence REAL/integration | REAL | COMPLETED + 100 + timestamp REAL | Linux+Windows REAL | completion verified directly on VTODO; ordinary Event remains |
| `history today` / task | REAL-PARTIAL | REAL-PARTIAL | task ambiguity integration | syntax integration | REAL menu Back | local journal still usable where designed | REAL SQLite | timezone formatting integration | Linux REAL-PARTIAL | History menu human think-time also checks no fake progress heartbeat |
| `history wordpress` / pending | REAL | REAL empty | N/A | syntax integration | REAL menu Back | REAL Outbox offline semantics | REAL | local-time compact line REAL | Linux REAL | production Outbox is inspected after real lifecycle operations |
| `log` / WordPress long-term log | REAL-PARTIAL | empty text integration | N/A | prompt validation integration | cancel integration | REAL Outbox/failure isolation | REAL | local clock formatting REAL | Linux REAL | WordPress cannot make Task completion fail |
| `help`, `help all`, category help, command help | REAL-PARTIAL | unknown command integration | N/A | invalid category/name integration | menu Back REAL | N/A | N/A | N/A | Linux REAL-PARTIAL | shared categorized library; no giant one-shot help dump |
| Exit / Ctrl-D / Ctrl-C at console | REAL-PARTIAL | N/A | N/A | N/A | REAL-PARTIAL | background remains independent integration | REAL background | N/A | Linux REAL-PARTIAL | foreground can exit without killing reminder service |

## 4. Settings and reminder interaction matrix

| Surface | Healthy interaction | Invalid/cancel | Failure / persistence | Status |
|---|---|---|---|---|
| Settings root/submenus | `settings` → category → numeric choice → Back | shared Menu controls | production SQLite reread | REAL-PARTIAL |
| Language/UI locale | choose English / Simplified Chinese; canonical ASCII commands stay stable | unsupported locale rejected | survives new process | UNIT/INTEGRATION; human-path expansion wanted |
| CalDAV URL/credentials/collections | set → test connection → report real collections | malformed URL / auth failure visible | server unavailable cannot become false success | REAL-PARTIAL + integration |
| Agenda upcoming window | choose/set hours → startup/menu reflects configured window | invalid value rejected | persists | REAL-PARTIAL |
| Notifications enabled | Settings → Notifications → On/Off | Back leaves unchanged | persists | REAL |
| Reminder sound | Settings → On/Off | Back leaves unchanged | persists | REAL |
| Terminal BEL enabled | Settings → On/Off | Back leaves unchanged | persists | REAL |
| BEL repeat count | preset menu → 5 → verify → restore 3 | invalid menu choice stays in menu | production setting reread | REAL |
| BEL interval | preset menu → 200 ms → verify → restore 400 ms | invalid menu choice stays in menu | production setting reread | REAL |
| Persistent alarm acknowledgement | actual repeated BEL → real Ctrl-C | Ctrl-C must not escape into Task control | process remains alive | REAL Linux |
| Desktop notification adapter | real OS banner/action | permissions/daemon unavailable | secondary failure must not change Task facts | MANUAL per desktop OS |
| Snooze/cancel reminder | create → snooze/cancel → next due state | invalid time/id | survives restart where required | UNIT/INTEGRATION; human-path GAP |

## 5. Extension and Public Python API matrix

| Surface | Healthy | Conflict/invalid | Failure isolation | Status |
|---|---|---|---|---|
| `extensions` | list official + user origin/status | N/A | one bad extension must not hide others | UNIT/INTEGRATION; human path being expanded |
| `extension guide` | shows Easy API first and Task/Event model | extra args rejected | N/A | REAL-PARTIAL |
| `extension new NAME` | creates one `.py` file, disabled | invalid name / existing core command rejected | file write failure visible | UNIT/INTEGRATION; human path wanted |
| `extension dev/path` | creates non-destructive VS Code settings / shows path | extra args rejected | filesystem error isolated | UNIT/INTEGRATION |
| `official/user/info/reset` | inspect origin/defaults; reset official only | unknown/user reset rejected | no Core crash | UNIT/INTEGRATION |
| `add/load/enable/disable/reload/unload` | lifecycle changes command availability | missing name/path/command collision rejected | import/runtime error becomes Extension record | UNIT/INTEGRATION; real installed lifecycle GAP |
| `extension errors` | shows traceback/hook failure | unknown name visible | Core commands remain usable | UNIT/INTEGRATION; real installed isolation GAP |
| Easy API query blocks | `tasks/events/today/agenda/next_*` use current context | not-found/ambiguous model | no XML/IPC exposed | integration + extension template |
| Easy API Task/Event mutations | `add/edit/start/pause/resume/complete/remove/set_due` | rejects Event-as-Task and vice versa | stable v1 errors | integration; real extension lifecycle GAP |
| Easy temporal/menu blocks | `parse_*`, `ask_*`, `choose*`, `confirm` | parser/menu recovery | N/A | integration; CLI PromptKit REAL |
| Easy reminders/notify/write_log | public synchronous bricks | invalid target/time | adapter/outbox failure isolated | integration/partial real |
| Object API (`AssistantContext`) | namespaces tasks/events/agenda/reminders/notifications/wordpress/ui/time/commands/activity/settings/session | stable error classes | no direct SQLite/XML required | integration |
| Full API v1 / hooks | versioned import, hooks and advanced services | collision/invalid hook | hook exception must not roll back Task action | integration + lifecycle REAL secondary effects |

## 6. Failure-mode matrix

These are mandatory because happy-path acceptance alone is insufficient.

| Failure | User interaction expected | Source of truth rule | Evidence |
|---|---|---|---|
| Background absent | run ordinary CLI; Assistant auto-starts it | no user `systemctl` requirement | REAL |
| Stale/unreachable IPC | visible retry/restart/degraded message, no traceback | never invent current Task | REAL-PARTIAL |
| Startup agenda timeout | startup says unavailable; console stays usable | unknown ≠ empty | REAL regression + integration |
| CalDAV offline on read | show cached state only when available and label stale | cache is not truth | integration; real network-cut acceptance wanted |
| CalDAV offline on write | reject/queue only by explicit safe policy; never print success | CalDAV remains truth | integration; real network-cut acceptance wanted |
| WordPress offline | Task action still succeeds; Outbox retains log | WordPress never owns Task status | REAL/integration |
| Extension import/runtime failure | mark/report extension error; core commands continue | Core action unaffected | integration; real installed extension failure wanted |
| Hook failure after lifecycle | show/report secondary failure; do not roll back completed Core write | CalDAV action remains authoritative | integration + real lifecycle milestone ordering |
| Notification failure | reminder delivery issue reported/retry policy; Task unchanged | notification is adapter side effect | integration/manual |
| User presses Ctrl-C during alarm | acknowledge alarm only | no accidental Task pause/exit | REAL |
| User presses Ctrl-C in Waiting Mode | open explicit decision menu | no hidden completion/pause | REAL |
| User waits at a menu | no fake 'still working' heartbeat | user think-time is not backend latency | REAL |

## 7. Temporal boundary cases

All date-entry features must share the same TemporalParser. The following examples are
release-relevant, not parser trivia:

| Input / situation | Expected result |
|---|---|
| `August5`, `Aug5`, `August 5`, `Aug 5` in a new/edited future schedule | nearest future August 5 |
| explicit `2026-08-05` | exactly 2026-08-05 even if it is past |
| `8/5` in future scheduling context | nearest future August 5 |
| `tomorrow` | local tomorrow |
| `Friday` with future bias on Friday | next Friday, not silently today |
| `next Friday` | following Friday per parser contract |
| date-only input | CalDAV DATE; never converted silently to midnight DATE-TIME |
| date-time input | retains date-time semantics |
| historical query with past bias | nearest valid past interpretation |
| genuinely ambiguous year/result | ask only when the ambiguity changes the action |

`acceptance_crud_undo_real.py` specifically protects the regression where ordinary
Add/Edit UI called `ask_date()` without `bias="future"`, causing `August5` entered on
August 31 to point backward into the same year.

## 8. Platform matrix

| Platform | Unit/integration | Installed real CLI | Real CalDAV lifecycle | Desktop notification | Current release-gate status |
|---|---|---|---|---|---|
| Linux (Ubuntu CI) | yes | yes, PTY + one-shot | yes | BEL yes; desktop banner manual | strong |
| Windows 10/11 family | yes | yes, one-shot acceptance added in PR #47 | yes, server facts checked | desktop toast manual | must pass PR #47 |
| macOS | portable adapters/tests | no hosted human-path here | no hosted human-path here | manual | GAP before claiming macOS field validation |
| low-end dual-core / ~4 GB target | functional code/tests | requires representative hardware | requires representative hardware | manual | MANUAL performance gate |

## 9. Real acceptance scripts and what they prove

- `scripts/acceptance_conversation_real.py` — installed PTY, startup, guided start,
  Waiting Mode, pause/current/resume/done, real VTODO + Work VEVENT.
- `scripts/acceptance_crud_undo_real.py` — empty CRUD, Task/Event create/edit,
  PromptKit recovery, `August5`, date-only/future bias, numbered references,
  Menu help/Back, delete cancel/confirm and real Undo restoration.
- `scripts/acceptance_waiting_interrupt_real.py` — actual countdown, Ctrl-C decision,
  help, TIME UP semantics and pause.
- `scripts/acceptance_reminder_alert_settings_real.py` — ordinary Settings menus for
  reminder sound/BEL/repeat/interval plus persisted values.
- `scripts/acceptance_persistent_terminal_bell_real.py` — repeated actual BEL and
  actual Ctrl-C acknowledgement.
- `scripts/acceptance_wordpress_worklog_real.py` — installed lifecycle commands,
  production Outbox, compact/custom log formatting and per-user settings.
- `scripts/acceptance_latency_real.py` — real startup/menu latency and human think-time
  without false progress output.
- `scripts/acceptance_feature_demo_real.py` — read-only production route diagnosis;
  it is deliberately **not** treated as proof of write features.
- `scripts/acceptance_windows_cli_real.py` — Windows-compatible installed one-shot
  path using real Radicale and production background/IPC for
  `today/tasks/events/start/current/pause/resume/done/background`.

## 10. Issues found while building this matrix

### HP-001 — scheduling UI lost TemporalParser future context

**Observed by source-path audit and protected by real CRUD acceptance.**

`TemporalParser` already implements `bias="future"`, and the frozen design explicitly
uses a new Due date as the motivating example. However ordinary Add Task/Event and
ordinary `edit` scheduling prompts called `ask_date()`/`ask_datetime()` without the
future bias. On August 31, `August5` could therefore become August 5 of the same year.

Fix in PR #47: scheduling-specific CLI composition now passes `bias="future"` while
leaving generic Public `parse_date(..., bias="any")` behavior unchanged.

### HP-002 — Windows had pytest but no real installed-user path in CI

A passing Windows unit suite did not prove that the installed console script,
background process, local profile state, IPC and real CalDAV lifecycle worked together.

Fix in PR #47: Windows Python 3.10 and 3.12 jobs now run
`acceptance_windows_cli_real.py` after pytest.

### HP-003 — `demo` is intentionally read-only and cannot be a release proof for writes

The feature demo is useful for route diagnosis but explicitly does not create/edit/
start/pause/complete/remove. Treating it as a full feature acceptance would be a false
positive.

Fix in PR #47: keep demo read-only, and add separate destructive acceptance against a
disposable Radicale server.

## 11. Merge rule

Do not merge a change and do not call it "fixed", "complete" or "release ready" merely
because pytest is green. For a user-facing regression, the matching installed human
path above must also pass, including authoritative state verification when the feature
writes data.
