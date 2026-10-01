"""Select WordPress transports behind the stable WordPressService contract."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..settings.keys import (
    WORDPRESS_APPLICATION_PASSWORD,
    WORDPRESS_APPLICATION_PASSWORD_FILE,
    WORDPRESS_BASE_URL,
    WORDPRESS_PATH,
    WORDPRESS_TRANSPORT,
    WORDPRESS_USERNAME,
)
from .rest_transport import ApplicationPasswordRESTAdapter
from .transports import WPCLIAdapter


def _read_application_password(settings: Any) -> str:
    value = settings.get(WORDPRESS_APPLICATION_PASSWORD, None)
    if isinstance(value, str) and value.strip():
        return "".join(value.split())

    file_value = settings.get(WORDPRESS_APPLICATION_PASSWORD_FILE, None)
    if isinstance(file_value, str) and file_value.strip():
        try:
            return "".join(
                Path(file_value).expanduser().read_text(encoding="utf-8").split()
            )
        except (OSError, UnicodeError):
            return ""
    return ""


def select_wordpress_adapter(settings: Any):
    """Select one concrete transport deterministically for one operation."""
    mode = str(settings.get(WORDPRESS_TRANSPORT, "auto") or "auto").strip().casefold()
    base_url = settings.get(WORDPRESS_BASE_URL, None)
    username = settings.get(WORDPRESS_USERNAME, None)
    application_password = _read_application_password(settings)

    if mode == "application-password":
        return ApplicationPasswordRESTAdapter(
            base_url,
            username,
            application_password,
        )

    if mode == "wp-cli":
        return WPCLIAdapter(settings.get(WORDPRESS_PATH, None))

    if (
        isinstance(base_url, str)
        and base_url.strip()
        and isinstance(username, str)
        and username.strip()
        and application_password
    ):
        return ApplicationPasswordRESTAdapter(
            base_url,
            username,
            application_password,
        )

    return WPCLIAdapter(settings.get(WORDPRESS_PATH, None))


class ConfiguredWordPressAdapter:
    """Settings-backed adapter whose next operation sees settings changes immediately.

    A concrete transport is selected once per top-level adapter call. There is no
    fallback after a write begins: retrying through a second transport could duplicate
    a remote write whose response was lost.
    """

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    def _current(self):
        return select_wordpress_adapter(self.settings)

    def transport_name(self) -> str:
        adapter = self._current()
        return (
            "application-password"
            if isinstance(adapter, ApplicationPasswordRESTAdapter)
            else "wp-cli"
        )

    def create_log(self, text: str, **metadata: Any):
        return self._current().create_log(text, **metadata)

    def create_post(self, title: str, content: str = "", **fields: Any):
        return self._current().create_post(title, content, **fields)

    def update_post(self, post_id: Any, **changes: Any):
        return self._current().update_post(post_id, **changes)

    def attach_file(self, file_path: Any, **metadata: Any):
        return self._current().attach_file(file_path, **metadata)

    def read_daily_log(self, **options: Any):
        return self._current().read_daily_log(**options)

    def ensure_daily_log_reference(self, **options: Any):
        return self._current().ensure_daily_log_reference(**options)

    def test_connection(self) -> bool:
        return bool(self._current().test_connection())


def build_wordpress_adapter(settings: Any) -> ConfiguredWordPressAdapter:
    """Build the production settings-backed adapter.

    Auto mode preserves existing installations: REST is selected only when a complete
    Application Password configuration is present; otherwise WP-CLI remains active.
    """
    return ConfiguredWordPressAdapter(settings)


__all__ = [
    "ConfiguredWordPressAdapter",
    "build_wordpress_adapter",
    "select_wordpress_adapter",
]
