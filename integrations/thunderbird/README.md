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
