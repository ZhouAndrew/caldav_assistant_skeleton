from __future__ import annotations
from typing import Callable
_registrar = None
def _bind_hook_registrar(registrar):
    global _registrar
    _registrar = registrar

def on(event: str):
    def deco(fn: Callable):
        if _registrar is not None:
            if hasattr(_registrar, 'register'): _registrar.register(event, fn)
        return fn
    return deco
