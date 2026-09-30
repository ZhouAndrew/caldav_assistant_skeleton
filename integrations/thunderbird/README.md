# CalDAV Assistant for Thunderbird

Experimental standalone Thunderbird Space for the existing CalDAV Assistant Core.

## Current contract

- Thunderbird remains the user's normal CalDAV client.
- CalDAV VTODO remains the Task source of truth.
- Start / Pause / Cancel / Complete accept an explicit user-entered time.
- Every continuous work interval is one CalDAV Work VEVENT.
- Pause, Cancel and Complete close the current VEVENT at the entered time.
- Starting after a pause creates another VEVENT.
- Closed intervals are written to the existing WordPress daily log through the durable Outbox.
- Text notes and files are recorded to WordPress.
- Calendar -> WordPress daily-log linking is enabled by default.
- Direct Calendar -> attachment links are optional.

## Interactive Thunderbird workspace

The interaction belongs inside the Thunderbird XPI, not in a separate desktop
launcher.  The Space is a compact tabbed workspace:

- **工作** — searchable actionable Task list, current-work state, recorded time and
  Start/Pause/Resume/Cancel/Complete actions.
- **记录** — WordPress note/file capture and the small integration settings.
- **今天** — Activity Journal for the current day with one-click copy.
- **诊断** — structured Native Host timings, latest bottleneck analysis, raw logs,
  Copy/Open-folder/Clear actions.

Task and Work-session reads come from Thunderbird's already-open local
Calendar/Tasks cache through the narrow read-only Experiment API.  Normal refreshes
therefore do not wait for a new CalDAV HTTP round trip.  Mutations still go through
CalDAV Assistant Core so CalDAV remains authoritative.

The terminal setup remains only an installation/repair utility:

```bash
bash integrations/thunderbird/setup.sh
```

Native Host diagnostics are persisted at:

```text
~/.local/state/caldav-assistant/thunderbird/native-host.log
```

The XPI diagnostics tab reads that log through a separate Native Messaging process,
so log access remains available even when the main Core request channel is slow.

## Build the XPI

```bash
python3 integrations/thunderbird/build-xpi.py
```

The generated XPI is under `integrations/thunderbird/dist/`.

## Install the experimental build side-by-side on Linux

Run this from the experimental repository checkout:

```bash
bash integrations/thunderbird/install-native-host.sh
```

The installer creates its own isolated environment under
`~/.local/share/caldav-assistant-thunderbird-experimental/`, registers only the
experimental Thunderbird native host, builds and verifies the XPI, and copies one
unambiguous handoff file to the Desktop:

```text
CALDAV-ASSISTANT-EXPERIMENTAL-<version>.xpi
```

Install **that exact file**. In Thunderbird Add-ons Manager it must identify itself
as **CalDAV Assistant Experimental** with add-on ID
`caldav-assistant-experimental@zhouandrew.local`. `Thunderbird TaskFix Lab` is a
separate add-on with a separate purpose and does not provide this CalDAV Assistant
workspace. It may remain installed side-by-side.

The installer refuses to hand off an XPI if the package identity, nativeMessaging
permission, Calendar Experiment API, Space creation code, workspace tabs, or
Start/Pause/Cancel/Complete controls are missing. It does **not** replace the
existing `caldav-assistant` executable or its Python environment.

The native host calls the experimental Core directly in-process. This keeps the
production Assistant daemon untouched while reusing the existing CalDAV,
Settings, Activity Journal and WordPress data.

The Space keeps one persistent Native Messaging connection while it is open.
Attachments are streamed in 256 KiB chunks before being handed to WordPress,
rather than placing an entire image/PDF/audio/video file in one Native Messaging
message.

To remove only the experimental native host:

```bash
bash integrations/thunderbird/uninstall-experimental.sh
```


## Self-hosted automatic XPI updates

The Thunderbird add-on uses a **standalone lightweight Python HTTPS server**.
The serving process uses only the Python standard library (`http.server`,
`ssl`, `socket`, and related stdlib modules). It does not run through Apache,
WordPress, PHP, Docker, Caddy, the CalDAV server, or another application stack.

The fixed experimental add-on ID is:

```text
caldav-assistant-experimental@zhouandrew.local
```

and the update endpoint is:

```text
https://andrew.local:17443/experimental/updates.json
```

Mozilla/Gecko requires an add-on `update_url` to use HTTPS, so the first deployment
creates a small private CA and an HTTPS certificate for `andrew.local`. Certificate
generation uses the host's `openssl` command once; Thunderbird trust is installed
with NSS `certutil`. Neither tool is part of the running server.

### One-command deployment

For the normal human path, prefer the interactive setup:

```bash
bash integrations/thunderbird/setup.sh
```

For update-server-only repair, run:

```bash
bash integrations/thunderbird/update-server/deploy.sh
```

The deployment command:

1. builds the current XPI and `updates.json`,
2. copies the Python server into
   `~/.local/share/caldav-assistant-thunderbird-update-server/`,
3. creates and persists its private CA/certificate,
4. imports the CA into discovered Thunderbird NSS profiles,
5. installs a per-user systemd service with automatic restart,
6. starts the Python HTTPS server on TCP 17443,
7. verifies the health endpoint, JSON update manifest, and XPI over TLS.

If `certutil` is missing on Debian/Ubuntu/Linux Mint, the deployer installs the
small `libnss3-tools` package once. The running update server itself still needs
only Python.

### Publishing later versions

Once the server is deployed, future XPI releases are published with:

```bash
bash integrations/thunderbird/publish-self-hosted-update.sh
```

No restart is needed: the Python server reads the new static files on the next
request and the publisher verifies the live manifest and XPI immediately.

To stop the server while retaining the private CA and published files:

```bash
bash integrations/thunderbird/update-server/stop.sh
```

**Bootstrap note:** if the standalone update server was not successfully deployed
before this release, install the current XPI manually once after running the setup
wizard. From then on, Thunderbird can discover higher XPI versions through the
standalone Python server.

The native host and its Python environment remain outside the XPI. Thunderbird's
XPI updater therefore updates only the add-on package; native-host protocol changes
must remain backward compatible or be upgraded separately.

## Real acceptance required

Do not call this feature complete until it has been installed in a real Thunderbird
profile and the complete human path has passed:

1. Open the CalDAV Assistant Space.
2. Load real Radicale VTODOs.
3. Start at an entered time and confirm the Work VEVENT DTSTART.
4. Pause at an entered time and confirm VEVENT DTEND and the WordPress line.
5. Start again and confirm a second VEVENT.
6. Cancel and Complete paths.
7. Add a text note.
8. Add an image/PDF and confirm WordPress Media + post insertion.
9. Confirm Calendar event contains the WordPress log link by default.
10. Restart Thunderbird and confirm the Space/native bridge still works.
