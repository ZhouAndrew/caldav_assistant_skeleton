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
experimental Thunderbird native host, builds the XPI, and copies the XPI to the
Desktop. It does **not** replace the existing `caldav-assistant` executable or
its Python environment.

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

The Thunderbird add-on now uses a **standalone update server**. It does not publish
through Apache, WordPress, PHP, the CalDAV server, or an existing Caddy instance.

The only host runtime used by the server is Docker. The service itself runs in its
own Caddy container, listens on TCP 17443, keeps its files and private CA under
`~/.local/share/caldav-assistant-thunderbird-update-server/`, and restarts
automatically after reboot.

The fixed experimental add-on ID is:

```text
caldav-assistant-experimental@zhouandrew.local
```

The update manifest is:

```text
https://andrew.local:17443/experimental/updates.json
```

### One-click first deployment

From the repository root:

```bash
bash integrations/thunderbird/update-server/deploy.sh
```

That one command:

1. builds the current XPI and `updates.json`,
2. creates isolated server state under the user's local data directory,
3. starts/replaces the dedicated Caddy container with `--restart unless-stopped`,
4. creates and persists the server's own local CA,
5. adds that CA to the Linux trust store,
6. imports the CA directly into discovered Thunderbird NSS profiles,
7. verifies the HTTPS health endpoint, update manifest, and advertised XPI.

If `certutil` is missing on Debian/Ubuntu/Linux Mint, the deployment script installs
`libnss3-tools` solely for the Thunderbird certificate import. The update server
does not depend on that package after deployment.

### Publishing later versions

After the server is deployed, a new XPI version can be published with:

```bash
bash integrations/thunderbird/publish-self-hosted-update.sh
```

The publisher writes only into the standalone server's private `www` directory and
then verifies the live HTTPS manifest and XPI. It never writes under `/var/www`.

To stop the standalone update server without deleting its state or trust material:

```bash
bash integrations/thunderbird/update-server/stop.sh
```

Keeping the Caddy data directory preserves the same local CA across restarts and
redeployments, avoiding a surprise certificate rotation.

**Bootstrap note:** the earlier 0.1.0/0.1.1 builds did not point at this standalone
endpoint. Install 0.1.2 manually once. From 0.1.2 onward, Thunderbird can discover
higher XPI versions from the standalone server.

The native host and its Python environment remain outside the XPI. Thunderbird's
XPI updater therefore updates only the add-on UI/package; native-host protocol
changes must remain backward compatible or be upgraded separately.

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
