from dataclasses import dataclass
from enum import Enum
class BaseURLSource(str, Enum):
    SAVED="saved"
    DISCOVERED="discovered"
    MANUAL="manual"
@dataclass(frozen=True)
class ResolvedBaseURL:
    base_url: str
    source: BaseURLSource
