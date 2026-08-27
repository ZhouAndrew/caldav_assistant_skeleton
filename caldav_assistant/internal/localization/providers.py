"""Replaceable locale-resource providers; external packs are data-only TOML."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol
from .catalogs import BUILTIN_CATALOGS, BUILTIN_LOCALE_METADATA
from .codes import normalize_locale
try: import tomllib
except ModuleNotFoundError:
    try: import tomli as tomllib
    except ModuleNotFoundError: tomllib=None

@dataclass(frozen=True,slots=True)
class LocaleInfo:
    code:str; name:str; native_name:str; fallback:str|None=None; source:str="builtin"
@dataclass(frozen=True,slots=True)
class LocaleCatalog:
    info:LocaleInfo; messages:Mapping[str,str]
class LocaleProvider(Protocol):
    def available(self)->tuple[LocaleInfo,...]: ...
    def get(self,code:str)->LocaleCatalog|None: ...
    def reload(self)->None: ...
class BuiltinLocaleProvider:
    def available(self):
        return tuple(LocaleInfo(code,str(BUILTIN_LOCALE_METADATA[code]["name"]),str(BUILTIN_LOCALE_METADATA[code]["native_name"]),BUILTIN_LOCALE_METADATA[code]["fallback"],"builtin") for code in BUILTIN_CATALOGS)
    def get(self,code):
        code=normalize_locale(code); messages=BUILTIN_CATALOGS.get(code)
        if messages is None:return None
        meta=BUILTIN_LOCALE_METADATA[code]; return LocaleCatalog(LocaleInfo(code,str(meta["name"]),str(meta["native_name"]),meta["fallback"],"builtin"),messages)
    def reload(self): return None
class DirectoryLocaleProvider:
    def __init__(self,directory:str|Path)->None: self.directory=Path(directory).expanduser(); self._catalogs=None; self._errors={}
    @property
    def errors(self): self._ensure_loaded(); return dict(self._errors)
    def _load_file(self,path:Path)->LocaleCatalog:
        if tomllib is None: raise RuntimeError("external locale packs require tomllib or tomli")
        with path.open("rb") as stream:data=tomllib.load(stream)
        locale=data.get("locale"); messages=data.get("messages")
        if not isinstance(locale,dict):raise ValueError("missing [locale] table")
        if not isinstance(messages,dict):raise ValueError("missing [messages] table")
        raw=locale.get("code")
        if not isinstance(raw,str):raise ValueError("locale.code must be text")
        code=normalize_locale(raw); name=locale.get("name",code); native=locale.get("native_name",name); fallback=locale.get("fallback","en")
        if not isinstance(name,str) or not name.strip():raise ValueError("locale.name must be non-empty text")
        if not isinstance(native,str) or not native.strip():raise ValueError("locale.native_name must be non-empty text")
        if fallback is not None:
            if not isinstance(fallback,str):raise ValueError("locale.fallback must be text or null")
            fallback=normalize_locale(fallback)
        clean={}
        for key,value in messages.items():
            if not isinstance(key,str) or not key.strip() or not isinstance(value,str):raise ValueError("message keys/values must be text")
            clean[key.strip()]=value
        return LocaleCatalog(LocaleInfo(code,name.strip(),native.strip(),fallback,str(path)),clean)
    def _ensure_loaded(self):
        if self._catalogs is not None:return
        catalogs={}; errors={}
        try: files=sorted(self.directory.glob("*.toml"),key=lambda p:p.name.casefold())
        except OSError as exc: self._catalogs={};self._errors={str(self.directory):f"{type(exc).__name__}: {exc}"};return
        for path in files:
            try: cat=self._load_file(path)
            except Exception as exc: errors[str(path)]=f"{type(exc).__name__}: {exc}";continue
            catalogs[cat.info.code]=cat
        self._catalogs=catalogs;self._errors=errors
    def available(self):self._ensure_loaded();return tuple(cat.info for cat in self._catalogs.values())
    def get(self,code):self._ensure_loaded();return self._catalogs.get(normalize_locale(code))
    def reload(self):self._catalogs=None;self._errors={}
__all__=["LocaleInfo","LocaleCatalog","LocaleProvider","BuiltinLocaleProvider","DirectoryLocaleProvider"]
