from __future__ import annotations
from typing import Protocol, Sequence
class BaseURLDiscoveryAdapter(Protocol):
    def discover_base_urls(self) -> Sequence[str]: ...
