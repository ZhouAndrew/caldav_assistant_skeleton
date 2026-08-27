from pathlib import Path
from caldav_assistant.internal.commands import CommandRegistry,CommandService
from caldav_assistant.internal.extensions import ExtensionManager,HookRegistry
class FakeSettings:
    def __init__(self):self.values={}
    def get(self,key,default=None):return self.values.get(key,default)
    def set(self,key,value):self.values[key]=value

def make(tmp_path):
    commands=CommandService(CommandRegistry()); hooks=HookRegistry(); settings=FakeSettings()
    return ExtensionManager(commands,hooks,settings,root=tmp_path/"extensions"),commands,hooks,settings

def write(path:Path,text:str):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)

def test_discover_enable_load_disable_and_persist_state(tmp_path):
    manager,commands,_,settings=make(tmp_path)
    write(manager.root/"demo.py","from caldav_assistant.easy import command\n@command('urgent')\ndef urgent():\n    return 'ok'\n")
    assert [r.name for r in manager.discover()]==["demo"]
    assert manager.enable("demo").status=="loaded";assert commands.run("urgent")=="ok"
    assert settings.get("extensions.enabled")=={"demo":True}
    assert manager.disable("demo").status=="disabled";assert "urgent" not in commands.registry

def test_failed_import_does_not_damage_core(tmp_path):
    manager,commands,_,_=make(tmp_path);commands.register_builtin("today",lambda:"core")
    write(manager.root/"bad.py","from caldav_assistant.easy import command\n@command('partial')\ndef partial(): return 1\nraise RuntimeError('boom')\n")
    record=manager.enable("bad");assert record.status=="error";assert commands.run("today")=="core";assert "partial" not in commands.registry
