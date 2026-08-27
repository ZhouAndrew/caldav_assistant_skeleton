from caldav_assistant.internal.commands import CommandRegistry,CommandService
from caldav_assistant.internal.extensions import ExtensionManager,HookRegistry
from caldav_assistant.internal.extensions.cli import register_extension_cli_commands
class FakeSettings:
    def __init__(self):self.values={}
    def get(self,key,default=None):return self.values.get(key,default)
    def set(self,key,value):self.values[key]=value

def test_management_commands_share_canonical_registry(tmp_path):
    commands=CommandService(CommandRegistry());manager=ExtensionManager(commands,HookRegistry(),FakeSettings(),root=tmp_path/"extensions")
    register_extension_cli_commands(commands,manager)
    assert "extensions" in commands.registry;assert "extension" in commands.registry
