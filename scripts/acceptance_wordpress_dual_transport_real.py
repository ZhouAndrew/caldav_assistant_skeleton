#!/usr/bin/env python3
"""Real WordPress acceptance for both supported transports.

Requires an actual WordPress installation prepared by CI.  It writes through the
production WordPressService + durable SQLite Outbox using REST/Application Password,
reads the result through WP-CLI, then does the reverse.  It also verifies attachments
from both transports are visible through the other transport.
"""
from __future__ import annotations

from pathlib import Path
import os
import tempfile

from caldav_assistant.internal.storage.sqlite import SQLiteOutboxRepository, SQLiteStore
from caldav_assistant.internal.wordpress.rest_transport import ApplicationPasswordRESTAdapter
from caldav_assistant.internal.wordpress.service import WordPressService
from caldav_assistant.internal.wordpress.transports import WPCLIAdapter


def require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def service(adapter, db_path: Path) -> WordPressService:
    store = SQLiteStore(db_path)
    store.migrate()
    return WordPressService(adapter, SQLiteOutboxRepository(store))


def assert_contains(value: str, needle: str, label: str) -> None:
    if needle not in value:
        raise AssertionError(f"{label} missing {needle!r}")


def main() -> int:
    base_url = require("WP_TEST_BASE_URL")
    username = require("WP_TEST_USERNAME")
    application_password = require("WP_TEST_APPLICATION_PASSWORD")
    wpcli = require("WP_TEST_WPCLI")
    wordpress_path = require("WP_TEST_PATH")

    rest = ApplicationPasswordRESTAdapter(
        base_url,
        username,
        application_password,
    )
    cli = WPCLIAdapter(
        wordpress_path,
        executable=wpcli,
        timeout=60,
    )

    if not rest.test_connection():
        raise AssertionError("Application Password REST authentication failed")
    print("PASS: real WordPress REST/Application Password authentication")

    if not cli.test_connection():
        raise AssertionError("WP-CLI connection failed")
    print("PASS: real WordPress WP-CLI connection")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-real-wordpress-") as raw:
        tmp = Path(raw)
        rest_service = service(rest, tmp / "rest.sqlite3")
        cli_service = service(cli, tmp / "cli.sqlite3")

        rest_text = "CALDAV ASSISTANT REAL REST WRITE"
        result = rest_service.log(rest_text)
        if not result.success:
            raise AssertionError(result.message)
        if rest_service.pending():
            raise AssertionError("REST success left an Outbox item pending")

        cli_read = cli.read_daily_log()
        if not cli_read:
            raise AssertionError("WP-CLI could not read REST-created daily log")
        assert_contains(cli_read["content"], rest_text, "WP-CLI read-back")
        daily_id = cli_read["id"]
        print(f"PASS: REST write -> WP-CLI read-back on daily Post {daily_id}")

        cli_text = "CALDAV ASSISTANT REAL WPCLI WRITE"
        result = cli_service.log(cli_text)
        if not result.success:
            raise AssertionError(result.message)
        if cli_service.pending():
            raise AssertionError("WP-CLI success left an Outbox item pending")

        rest_read = rest.read_daily_log()
        if not rest_read:
            raise AssertionError("REST could not read WP-CLI-updated daily log")
        if rest_read["id"] != daily_id:
            raise AssertionError(
                f"transports disagreed on daily Post id: {daily_id} vs {rest_read['id']}"
            )
        assert_contains(rest_read["content"], rest_text, "REST read-back")
        assert_contains(rest_read["content"], cli_text, "REST read-back")
        print("PASS: WP-CLI write -> REST read-back on the same daily Post")

        rest_file = tmp / "rest-attachment.txt"
        rest_file.write_text("attachment from REST", encoding="utf-8")
        attachment = rest_service._attach_file(str(rest_file))
        if not attachment.success:
            raise AssertionError(attachment.message)
        if rest_service.pending():
            raise AssertionError("REST attachment left an Outbox item pending")
        cli_after_attachment = cli.read_daily_log()
        assert_contains(
            cli_after_attachment["content"],
            rest_file.name,
            "WP-CLI attachment read-back",
        )
        print("PASS: REST media upload/parent/append -> WP-CLI read-back")

        cli_file = tmp / "wpcli-attachment.txt"
        cli_file.write_text("attachment from WP-CLI", encoding="utf-8")
        attachment = cli_service._attach_file(str(cli_file))
        if not attachment.success:
            raise AssertionError(attachment.message)
        if cli_service.pending():
            raise AssertionError("WP-CLI attachment left an Outbox item pending")
        rest_after_attachment = rest.read_daily_log()
        assert_contains(
            rest_after_attachment["content"],
            cli_file.name,
            "REST attachment read-back",
        )
        print("PASS: WP-CLI media import/parent/append -> REST read-back")

        marker = "CALDAV ASSISTANT REAL UPDATE"
        updated = rest_service.update_post(daily_id, post_content=marker)
        if not updated.success:
            raise AssertionError(updated.message)
        cli_updated = cli.read_daily_log()
        if not cli_updated or cli_updated["content"] != marker:
            raise AssertionError("REST update_post was not visible to WP-CLI")
        print("PASS: REST update_post -> WP-CLI exact read-back")

        updated = cli_service.update_post(daily_id, post_content=rest_text + "\n" + cli_text)
        if not updated.success:
            raise AssertionError(updated.message)
        rest_updated = rest.read_daily_log()
        assert_contains(rest_updated["content"], rest_text, "REST final read-back")
        assert_contains(rest_updated["content"], cli_text, "REST final read-back")
        print("PASS: WP-CLI update_post -> REST exact read-back")

    print("REAL WORDPRESS DUAL-TRANSPORT ACCEPTANCE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
