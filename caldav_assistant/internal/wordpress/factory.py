"""Select the configured WordPress transport without changing WordPressService."""
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


def build_wordpress_adapter(settings: Any):
    """Return one transport deterministically.

    auto preserves existing installations: use REST only when a complete
    Application Password configuration is present; otherwise keep WP-CLI.
    There is deliberately no write-time fallback between transports because a
    remote write may have succeeded before a transport error was observed.
    """
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


__all__ = ["build_wordpress_adapter"]
