"""Scratch-like CLI settings menu and one-shot settings command."""
from __future__ import annotations
import json
from typing import Any
from ...api.v1.errors import ValidationError
from .keys import UI_LOCALE
from .schema import DEFAULT_SETTINGS_SCHEMA,SettingSpec
_CATEGORY_ORDER=("Language","CalDAV","Notifications","WordPress","Commands","Extensions")
def _display_value(value):
    if isinstance(value,bool):return "On" if value else "Off"
    if value is None:return "Not configured"
    if isinstance(value,dict):return json.dumps(value,ensure_ascii=False,sort_keys=True)
    return str(value)
class SettingsActions:
    def __init__(self,ctx:Any)->None:self.ctx=ctx;self.schema=DEFAULT_SETTINGS_SCHEMA
    def _refresh_locale(self,key,value):
        if key != UI_LOCALE:return
        setter=getattr(self.ctx.ui,"set_locale",None)
        if callable(setter):setter(value,persist=False)
    def _show(self,value):
        show=getattr(self.ctx.ui,"show",None)
        if callable(show):show(value)
    def _choose(self,title,items):
        choose=getattr(self.ctx.ui,"choose",None)
        if not callable(choose):raise ValidationError("Interactive settings require ctx.ui.choose()")
        return choose(title,items)
    def _ask_text(self,prompt):
        ask=getattr(self.ctx.ui,"ask_text",None)
        if not callable(ask):raise ValidationError("Interactive settings require ctx.ui.ask_text()")
        return ask(prompt)
    def _get(self,spec):return self.ctx.settings.get(spec.key,spec.default_value()) if spec.public_read else None
    def _edit_spec(self,spec:SettingSpec):
        if not spec.public_write:raise ValidationError(f"{spec.key} is read-only")
        if spec.kind=="bool":
            selected=self._choose(spec.label,["On","Off"])
            if selected is None:return
            value=selected=="On"
        elif spec.kind=="choice":
            selected=self._choose(spec.label,list(spec.choices))
            if selected is None:return
            value=selected
        else:
            value=self._ask_text(f"{spec.label}: ")
            if value is None:return
        normalized=self.ctx.settings.set(spec.key,value);self._refresh_locale(spec.key,normalized);self._show(f"✓ {spec.label}: {_display_value(normalized)}")
    def menu(self):
        while True:
            category=self._choose("Settings",list(_CATEGORY_ORDER))
            if category is None:return None
            specs=list(self.schema.list(category=category)); labels=[f"{s.label}: {_display_value(self._get(s))}" for s in specs]
            selected=self._choose(category,labels)
            if selected is None:continue
            self._edit_spec(specs[labels.index(selected)])
    def command(self,*parts):
        if not parts:return self.menu()
        action=str(parts[0]).casefold()
        if action=="categories":return "\n".join(_CATEGORY_ORDER)
        if action=="list":
            category=" ".join(map(str,parts[1:])) or None
            return "\n".join(f"{item['key']} = {_display_value(item['value'])}" for item in self.ctx.settings.list(category))
        if len(parts)<2:raise ValidationError("settings command requires a key")
        key=str(parts[1])
        if action=="get":return f"{key} = {_display_value(self.ctx.settings.get(key))}"
        if action=="set":
            if len(parts)<3:raise ValidationError("settings set requires a value")
            value=" ".join(map(str,parts[2:]));normalized=self.ctx.settings.set(key,value);self._refresh_locale(key,normalized);return f"✓ {key} = {_display_value(normalized)}"
        if action=="reset":return f"✓ {key} = {_display_value(self.ctx.settings.reset(key))}"
        raise ValidationError(f"Unknown settings action: {action}")
def register_settings_cli_command(commands,ctx):
    actions=SettingsActions(ctx)
    register=getattr(commands,"register_builtin",None)
    if callable(register):register("settings",actions.command,description="Open or modify Assistant settings.")
    else:commands.registry.register("settings",actions.command,protected=True,description="Open or modify Assistant settings.")
    return actions
__all__=["SettingsActions","register_settings_cli_command"]
