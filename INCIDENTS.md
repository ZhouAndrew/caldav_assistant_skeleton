# Incident log

## P0-2026-09-27 — desktop notification flood after background startup

**Status:** fixed by the notification-safety hotfix on this branch; release verification is required before merge.

### User-visible symptom

A background Assistant generation could enqueue a large number of desktop reminders in a short time. On Linux/Cinnamon, notifications already handed to the desktop notification service may continue appearing even after the CalDAV Assistant process itself has stopped. This can make it look as if the stopped process is still generating popups.

### Root causes

1. `notifications.enabled` existed in Settings but was not wired into the production `NotificationService`. The Linux adapter could therefore still invoke `notify-send` while the setting was Off.
2. `ReminderService` considered every never-delivered request with `when <= now` deliverable, regardless of age. After restart, upgrade, sleep, or a long inactive period, historical Task/Event reminder debt could therefore be replayed into the OS notification queue.
3. Desktop notification queues are outside the Assistant process. Stopping the producer cannot retract notifications already accepted by the desktop environment.

### Permanent fix

- `NotificationService` now has an authoritative master gate; when disabled, no platform notification adapter is invoked.
- Production wiring reads `notifications.enabled` live on every send.
- Desktop notifications default to **Off** for new/unset configurations.
- The first startup after this hotfix performs a one-time safe-off migration. A later explicit user re-enable is preserved.
- Production reminder delivery has a 30-minute maximum lateness window. Older undelivered requests are consumed for de-duplication without creating OS popups.
- Regression tests cover the dynamic master gate and stale reminder debt.
- Real Linux acceptance uses a fake `notify-send` executable to prove the production bootstrap path makes zero adapter calls while notifications are disabled.

### Recovery note

If an affected build has already flooded the desktop notification queue, stopping/masking CalDAV Assistant prevents new producer activity but may not immediately remove notifications already queued by Cinnamon or another desktop notification daemon. Temporarily disabling desktop notifications is a recovery measure, not part of normal operation.

### Safety rule

Future notification work must preserve this invariant:

> `notifications.enabled = false` means zero operating-system notification-adapter calls.

Historical reminder debt must never be replayed as an unbounded popup burst.
