"""Validated Object-API boundary for ctx.settings."""
from __future__ import annotations
from typing import Any
from .service import SettingsService
class PublicSettingsAPI:
    def __init__(self,service:SettingsService)->None:
        if not isinstance(service,SettingsService):raise TypeError("service must be SettingsService")
        self._service=service
    def get(self,key:str,default:Any=None)->Any:return self._service.get_public(key,default)
    def set(self,key:str,value:Any)->Any:return self._service.set_public(key,value)
    def reset(self,key:str)->Any:return self._service.reset_public(key)
    def describe(self,key:str)->dict[str,Any]:return self._service.describe_public(key)
    def list(self,category:str|None=None)->list[dict[str,Any]]:return self._service.list_public(category)
__all__=["PublicSettingsAPI"]
