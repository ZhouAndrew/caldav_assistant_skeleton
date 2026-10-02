"""Reusable CalDAV transport/session management.

This module is the narrow wire-session boundary below CalDAV adapters. It is
inspired by Thunderbird's separation between calendar logic and CalDAV
sessions/requests, while staying native to python-caldav.

MODULE CONTRACT
- Own client construction, reuse, invalidation and connection lifetime.
- Consume the existing BaseURLProvider and existing credential object as-is.
- Must not read Settings/SQLite, perform discovery, prompt the user, or contain
  Task/Event business rules.
- Must not change the public CLI/API or require a config migration.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Protocol


class BaseURLProvider(Protocol):
    """Minimal dynamic endpoint dependency supplied by bootstrap."""

    def get_base_url(self) -> str:
        ...


CredentialEncoder = Callable[[Any], Mapping[str, Any]]
ClientFactory = Callable[..., Any]


class CalDAVTransportSession:
    """Own one reusable python-caldav client for the current endpoint.

    The session deliberately re-evaluates both the resolved Base URL and the
    encoded credentials before reusing a client. This gives us Thunderbird-
    style session ownership without changing the old configuration model.

    A changed endpoint or changed credentials closes the previous client before
    a replacement is created. Explicit one-shot probes can use new_client()
    without disturbing the cached client.
    """

    def __init__(
        self,
        base_url_provider: BaseURLProvider,
        credentials: Any,
        *,
        client_factory: ClientFactory,
        credential_encoder: CredentialEncoder,
        timeout: float = 10.0,
    ) -> None:
        self._base_url_provider = base_url_provider
        self._credentials = credentials
        self._client_factory = client_factory
        self._credential_encoder = credential_encoder
        self._timeout = timeout

        self._client: Any | None = None
        self._client_base_url: str | None = None
        self._client_credentials: dict[str, Any] | None = None

    @property
    def base_url(self) -> str:
        """Resolve the current URL every time; ServerDiscovery remains owner."""

        return self._base_url_provider.get_base_url()

    @property
    def credentials(self) -> Any:
        return self._credentials

    @credentials.setter
    def credentials(self, value: Any) -> None:
        """Replace credentials and invalidate an authenticated session."""

        self._credentials = value

        # Close unconditionally. Credential containers can be mutable and
        # equality is not a safe indication that an authenticated HTTP session
        # may continue to be reused.
        self.close()

    def _encoded_credentials(self, credentials: Any) -> dict[str, Any]:
        return dict(self._credential_encoder(credentials))

    def _client_kwargs(
        self,
        base_url: str,
        credentials: Any,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "url": base_url,
            "timeout": self._timeout,

            # ServerDiscovery already owns RFC6764/mDNS discovery.
            "enable_rfc6764": False,

            # Local/legacy CalDAV may legitimately use plain HTTP.
            # This does NOT disable HTTPS certificate verification.
            "require_tls": False,
        }
        kwargs.update(self._encoded_credentials(credentials))
        return kwargs

    def new_client(
        self,
        base_url: str,
        credentials: Any,
    ) -> Any:
        """Create an uncached client for an explicit endpoint probe."""

        return self._client_factory(
            **self._client_kwargs(base_url, credentials)
        )

    def client(self) -> Any:
        """Return the reusable client for the current endpoint/credentials."""

        base_url = self.base_url
        encoded = self._encoded_credentials(self._credentials)

        if (
            self._client is None
            or self._client_base_url != base_url
            or self._client_credentials != encoded
        ):
            self.close()
            self._client = self._client_factory(
                **self._client_kwargs(base_url, self._credentials)
            )
            self._client_base_url = base_url
            self._client_credentials = encoded

        return self._client

    def close(self) -> None:
        """Close and forget the current HTTP client/session."""

        client = self._client
        self._client = None
        self._client_base_url = None
        self._client_credentials = None

        if client is None:
            return

        close = getattr(client, "close", None)
        if callable(close):
            close()
