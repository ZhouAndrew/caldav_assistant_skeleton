"""Locale-code normalization for UI localization."""
from __future__ import annotations
import re

_ALIASES={
    "en":"en","en-us":"en","en-gb":"en",
    "zh":"zh-CN","zh-cn":"zh-CN","zh-hans":"zh-CN","zh-sg":"zh-CN",
}

def normalize_locale(value: str) -> str:
    if not isinstance(value,str) or not value.strip(): raise ValueError("locale must be non-empty text")
    clean=value.strip().replace("_","-")
    clean=re.sub(r"\.(?:UTF-?8|utf-?8)$","",clean)
    key=clean.casefold()
    if key in _ALIASES: return _ALIASES[key]
    parts=clean.split("-")
    if len(parts)==1: return parts[0].lower()
    return parts[0].lower()+"-"+parts[1].upper()+("-"+"-".join(parts[2:]) if len(parts)>2 else "")

__all__=["normalize_locale"]
