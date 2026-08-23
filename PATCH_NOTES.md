# Base URL provider patch

This patch fills the already-frozen `discovery / ServerDiscovery` responsibility.

## Dependency direction

```text
SQLiteKeyValueRepository
        |
        v
 SettingsService
        |
        v
 ServerDiscovery
        |
        | get_base_url() -> str
        v
 LibraryCalDAVAdapter
        |
        v
 CalDAV transport
```

`ServerDiscovery` does **not** depend on Task/Event/Agenda/Reminder/CLI/CalDAV XML.
It may read/write the saved server address only through `SettingsService`, which is
consistent with the frozen module-dependency table (`discovery -> adapters/settings`).

## What changed

- `discovery/service.py`: becomes the authoritative producer of `base_url`.
- `discovery/contracts.py`: tiny protocol for future `.local` / LAN discovery adapters.
- `discovery/models.py`: internal result/provenance value object.
- `discovery/__init__.py`: exports the discovery boundary.
- `settings/keys.py`: canonical internal setting keys.
- `settings/__init__.py`: exports those keys.
- `caldav/library_adapter.py`: consumes `get_base_url()`; never reads settings itself.
- `bootstrap.py`: constructs `ServerDiscovery(settings)` and injects it.
- `tests/test_base_url_provider.py`: contract tests.

## Intentionally not implemented here

- concrete mDNS / DNS-SD / LAN discovery;
- first-run interactive setup;
- credentials storage;
- CalDAV HTTP/XML transport itself.

Those are separate frozen responsibilities and should not be smuggled into the
base-URL provider.
