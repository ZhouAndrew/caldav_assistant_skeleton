from __future__ import annotations

from pathlib import Path

from caldav_assistant.internal.settings.keys import (
    WORDPRESS_APPLICATION_PASSWORD,
    WORDPRESS_APPLICATION_PASSWORD_FILE,
    WORDPRESS_BASE_URL,
    WORDPRESS_PATH,
    WORDPRESS_TRANSPORT,
    WORDPRESS_USERNAME,
)
from caldav_assistant.internal.wordpress.factory import (
    ConfiguredWordPressAdapter,
    build_wordpress_adapter,
    select_wordpress_adapter,
)
from caldav_assistant.internal.wordpress.rest_transport import (
    ApplicationPasswordRESTAdapter,
)
from caldav_assistant.internal.wordpress.transports import WPCLIAdapter


class Settings:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_auto_preserves_wp_cli_without_complete_rest_credentials():
    adapter = select_wordpress_adapter(Settings({
        WORDPRESS_PATH: "/var/www/html/wordpress",
    }))
    assert isinstance(adapter, WPCLIAdapter)
    assert adapter.wordpress_path == str(Path("/var/www/html/wordpress"))


def test_auto_keeps_configured_wp_cli_even_when_rest_credentials_are_complete():
    adapter = select_wordpress_adapter(Settings({
        WORDPRESS_PATH: "/var/www/html/wordpress",
        WORDPRESS_BASE_URL: "https://andrew.local",
        WORDPRESS_USERNAME: "wp_user",
        WORDPRESS_APPLICATION_PASSWORD: "wrong-or-unverified-secret",
    }))
    assert isinstance(adapter, WPCLIAdapter)
    assert adapter.wordpress_path == str(Path("/var/www/html/wordpress"))


def test_auto_uses_application_password_when_complete():
    adapter = select_wordpress_adapter(Settings({
        WORDPRESS_BASE_URL: "https://andrew.local",
        WORDPRESS_USERNAME: "wp_user",
        WORDPRESS_APPLICATION_PASSWORD: "abcd efgh",
    }))
    assert isinstance(adapter, ApplicationPasswordRESTAdapter)
    assert adapter.base_url == "https://andrew.local"
    assert adapter.username == "wp_user"
    assert adapter.application_password == "abcdefgh"


def test_application_password_can_be_loaded_from_file(tmp_path):
    password_file = tmp_path / "application-password.txt"
    password_file.write_text("abcd efgh ijkl\n", encoding="utf-8")
    adapter = select_wordpress_adapter(Settings({
        WORDPRESS_TRANSPORT: "application-password",
        WORDPRESS_BASE_URL: "https://andrew.local",
        WORDPRESS_USERNAME: "wp_user",
        WORDPRESS_APPLICATION_PASSWORD_FILE: str(password_file),
    }))
    assert isinstance(adapter, ApplicationPasswordRESTAdapter)
    assert adapter.application_password == "abcdefghijkl"


def test_explicit_wp_cli_wins_even_when_rest_credentials_exist():
    adapter = select_wordpress_adapter(Settings({
        WORDPRESS_TRANSPORT: "wp-cli",
        WORDPRESS_PATH: "/srv/wordpress",
        WORDPRESS_BASE_URL: "https://example.test",
        WORDPRESS_USERNAME: "wp_user",
        WORDPRESS_APPLICATION_PASSWORD: "secret",
    }))
    assert isinstance(adapter, WPCLIAdapter)
    assert adapter.wordpress_path == str(Path("/srv/wordpress"))


def test_production_adapter_applies_settings_changes_without_restart():
    values = {
        WORDPRESS_PATH: "/srv/wordpress",
        WORDPRESS_TRANSPORT: "auto",
    }
    settings = Settings(values)
    adapter = build_wordpress_adapter(settings)

    assert isinstance(adapter, ConfiguredWordPressAdapter)
    assert adapter.transport_name() == "wp-cli"

    values.update({
        WORDPRESS_BASE_URL: "https://andrew.local",
        WORDPRESS_USERNAME: "wp_user",
        WORDPRESS_APPLICATION_PASSWORD: "secret",
    })
    assert adapter.transport_name() == "application-password"

    values[WORDPRESS_TRANSPORT] = "wp-cli"
    assert adapter.transport_name() == "wp-cli"
