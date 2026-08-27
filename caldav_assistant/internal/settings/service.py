"""Authoritative settings behavior above a replaceable key/value repository."""
from __future__ import annotations
from copy import deepcopy
from typing import Any
from ...api.v1.errors import ValidationError
from .schema import DEFAULT_SETTINGS_SCHEMA,SettingsSchema
_MISSING=object()
class SettingsService:
    def __init__(self,repository:Any,schema:SettingsSchema=DEFAULT_SETTINGS_SCHEMA)->None:self._repository=repository;self.schema=schema
    @staticmethod
    def _key(key:Any)->str:
        if not isinstance(key,str) or not key.strip():raise ValidationError("Setting key must be non-empty text")
        return key.strip()
    def _stored(self,key):return self._repository.get(key,_MISSING)
    def get(self,key,default=None):
        clean=self._key(key);value=self._stored(clean)
        if value is not _MISSING:return deepcopy(value)
        if default is not None:return deepcopy(default)
        spec=self.schema.find(clean);return spec.default_value() if spec is not None else default
    def set(self,key,value):
        clean=self._key(key);spec=self.schema.find(clean);normalized=spec.normalize(value) if spec else deepcopy(value)
        if normalized is None and spec is not None and spec.default is None:self._repository.delete(clean);return None
        self._repository.set(clean,deepcopy(normalized));return deepcopy(normalized)
    def delete(self,key):self._repository.delete(self._key(key))
    def get_public(self,key,default=None):
        clean=self._key(key);spec=self.schema.get(clean)
        if not spec.public_read:raise ValidationError(f"Setting {clean!r} is not publicly readable")
        return self.get(clean,default)
    def set_public(self,key,value):
        clean=self._key(key);spec=self.schema.get(clean)
        if not spec.public_write:raise ValidationError(f"Setting {clean!r} is not publicly writable")
        normalized=spec.normalize(value)
        if normalized is None and spec.default is None:self._repository.delete(clean);return None
        self._repository.set(clean,deepcopy(normalized));return deepcopy(normalized)
    def reset_public(self,key):
        clean=self._key(key);spec=self.schema.get(clean)
        if not spec.public_write:raise ValidationError(f"Setting {clean!r} is not publicly writable")
        self._repository.delete(clean);return spec.default_value()
    def describe_public(self,key):
        spec=self.schema.get(self._key(key))
        if not(spec.public_read or spec.public_write):raise ValidationError(f"Setting {spec.key!r} is not public")
        return spec.metadata()
    def list_public(self,category=None):
        result=[]
        for spec in self.schema.list(category=category):
            if not spec.public_read:continue
            item=spec.metadata();item["value"]=self.get(spec.key);result.append(item)
        return result
__all__=["SettingsService"]
