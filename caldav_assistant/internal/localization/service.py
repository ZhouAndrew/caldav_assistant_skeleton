"""Canonical user-interface localization service."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Iterable, Mapping
from .codes import normalize_locale
from .providers import BuiltinLocaleProvider,DirectoryLocaleProvider,LocaleCatalog,LocaleInfo,LocaleProvider
UI_LOCALE_KEY="ui.locale"; DEFAULT_LOCALE="en"
class _SafeFormatDict(dict):
    def __missing__(self,key):return "{"+key+"}"
def _safe_format(text:str,values:Mapping[str,Any])->str:
    if not values:return text
    try:return text.format_map(_SafeFormatDict(values))
    except (ValueError,KeyError,IndexError):return text
class LocaleService:
    def __init__(self,settings:Any=None,*,providers:Iterable[LocaleProvider]|None=None,locale_dir:str|Path|None=None,default_locale:str=DEFAULT_LOCALE)->None:
        self.settings=settings;self.default_locale=normalize_locale(default_locale)
        if providers is None:
            directory=Path(locale_dir).expanduser() if locale_dir is not None else Path.home()/".caldav-assistant/locales"
            providers=(DirectoryLocaleProvider(directory),BuiltinLocaleProvider())
        self.providers=tuple(providers)
        if not self.providers:raise ValueError("at least one locale provider is required")
        self._locale=None;self._catalog_cache={}
    def _setting_get(self,key,default=None):
        getter=getattr(self.settings,"get",None)
        if not callable(getter):return default
        try:return getter(key,default)
        except Exception:return default
    def _setting_set(self,key,value):
        setter=getattr(self.settings,"set",None)
        if not callable(setter):raise RuntimeError("settings are not writable")
        setter(key,value)
    @property
    def locale(self):
        if self._locale is not None:return self._locale
        stored=self._setting_get(UI_LOCALE_KEY,None); candidate=stored if isinstance(stored,str) and stored.strip() else self.default_locale
        try:resolved=self.resolve_locale(candidate)
        except (TypeError,ValueError):resolved=self.resolve_locale(self.default_locale)
        self._locale=resolved;return resolved
    @property
    def current_locale(self):return self.locale
    def _catalog(self,code):
        code=normalize_locale(code)
        if code in self._catalog_cache:return self._catalog_cache[code]
        for provider in self.providers:
            catalog=provider.get(code)
            if catalog is not None:self._catalog_cache[code]=catalog;return catalog
        self._catalog_cache[code]=None;return None
    def available_locales(self)->tuple[LocaleInfo,...]:
        seen={};
        for provider in self.providers:
            for info in provider.available():seen.setdefault(info.code,info)
        return tuple(seen.values())
    available=available_locales
    def resolve_locale(self,code:str)->str:
        normalized=normalize_locale(code)
        if self._catalog(normalized) is not None:return normalized
        language=normalized.split("-",1)[0]
        if self._catalog(language) is not None:return language
        raise ValueError(f"unsupported locale: {code}")
    def set_locale(self,code:str,*,persist:bool=True)->str:
        resolved=self.resolve_locale(code);self._locale=resolved
        if persist:self._setting_set(UI_LOCALE_KEY,resolved)
        return resolved
    def _fallback_chain(self,code:str):
        seen=set();current=self.resolve_locale(code)
        while current not in seen:
            seen.add(current);yield current;catalog=self._catalog(current);fallback=catalog.info.fallback if catalog else None
            if fallback is None:break
            try:current=self.resolve_locale(fallback)
            except ValueError:break
        if "en" not in seen and self._catalog("en") is not None:yield "en"
    def translate(self,key:str,*,locale:str|None=None,default:str|None=None,**values:Any)->str:
        if not isinstance(key,str) or not key.strip():raise ValueError("translation key must be non-empty text")
        selected=locale or self.locale
        for code in self._fallback_chain(selected):
            catalog=self._catalog(code)
            if catalog is not None and key in catalog.messages:return _safe_format(catalog.messages[key],values)
        text=key if default is None else str(default);return _safe_format(text,values)
    t=translate
    def has(self,key,*,locale=None):return any((cat:=self._catalog(code)) is not None and key in cat.messages for code in self._fallback_chain(locale or self.locale))
    def locale_info(self,code=None):
        resolved=self.resolve_locale(code or self.locale);catalog=self._catalog(resolved);assert catalog is not None;return catalog.info
    def reload(self):
        for provider in self.providers:provider.reload()
        self._catalog_cache.clear();self._locale=None
__all__=["UI_LOCALE_KEY","DEFAULT_LOCALE","normalize_locale","LocaleInfo","LocaleService"]
