"""Extension lifecycle and hook infrastructure."""
from .hooks import HookEntry, HookFailure, HookRegistry
from .manager import ExtensionManager, ExtensionRecord

__all__ = [
    "HookEntry",
    "HookFailure",
    "HookRegistry",
    "ExtensionRecord",
    "ExtensionManager",
]
