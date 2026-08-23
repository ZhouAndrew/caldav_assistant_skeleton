from __future__ import annotations
from typing import Any, Protocol
class BaseURLProvider(Protocol):
    def get_base_url(self) -> str: ...
class LibraryCalDAVAdapter:
    def __init__(self, base_url_provider: BaseURLProvider, credentials: Any): self._base_url_provider=base_url_provider; self.credentials=credentials
    @property
    def base_url(self): return self._base_url_provider.get_base_url()
