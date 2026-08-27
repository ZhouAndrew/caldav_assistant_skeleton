"""Composition root: concrete infrastructure -> shared Core services."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from ..api import AssistantContext
from ..api.v1.hooks import _bind_hook_registrar
from .activity import ActivityService
from .agenda import AgendaEngine, AgendaService, NextEngine
from .caldav import SyncEngine
from .caldav.library_adapter import LibraryCalDAVAdapter
from .cli.actions import BuiltinActions
from .cli.io import StdConsoleIO
from .commands import CommandRegistry, CommandService
from .commands.decorators import bind_command_registry
from .discovery import ServerDiscovery
from .discovery.adapters import MDNSCalDAVDiscoveryAdapter
from .events import EventService
from .extensions import ExtensionManager, HookRegistry
from .notifications import NotificationService
from .notifications.platform_adapters import LinuxNotificationAdapter, MacOSNotificationAdapter, WindowsNotificationAdapter
from .prompts import Menu, PromptKit
from .reminders import ReminderEngine, ReminderService
from .runtime.client import RuntimeClient
from .runtime.current_context import bind_current_context
from .runtime.dispatcher import RuntimeDispatcher
from .runtime.headless_ui import HeadlessUI
from .runtime.ipc_platform import UnixSocketIPCClient, UnixSocketIPCServer, WindowsNamedPipeIPCClient, WindowsNamedPipeIPCServer
from .runtime.proxies import RemoteActivityAPI, RemoteAgendaAPI, RemoteEventsAPI, RemoteNotificationsAPI, RemoteRemindersAPI, RemoteSettingsAPI, RemoteTasksAPI, RemoteWordPressAPI
from .runtime.scheduler import PlatformWakeScheduler
from .runtime.service import AssistantService
from .runtime.service_launcher import ServiceLauncher
from .session import SessionService
from .settings import SettingsService
from .settings.keys import CALDAV_CREDENTIALS
from .storage.sqlite import SQLiteActivityRepository, SQLiteCacheRepository, SQLiteKeyValueRepository, SQLiteOutboxRepository, SQLiteStore, SQLiteUndoRepository
from .tasks import TaskService
from .temporal import TemporalParser, TemporalService
from .undo import UndoManager
from .wordpress import WordPressService
from .wordpress.transports import WPCLIAdapter

@dataclass
class ServiceApplication:
    ctx: AssistantContext; sync: SyncEngine; reminders: ReminderService; wordpress: WordPressService; extensions: ExtensionManager; background: AssistantService
@dataclass
class CLIApplication:
    ctx: AssistantContext; runtime: RuntimeClient; commands: CommandService; extensions: ExtensionManager; io: Any

def _state_dir(): return Path.home()/'.caldav-assistant'
def _notification_adapter_for_platform():
    import sys
    if sys.platform.startswith('win'): return WindowsNotificationAdapter()
    if sys.platform=='darwin': return MacOSNotificationAdapter()
    return LinuxNotificationAdapter()
def _ipc_endpoint(): return 'caldav-assistant-v1'
def _ipc_server_for_platform():
    import sys
    return WindowsNamedPipeIPCServer(_ipc_endpoint()) if sys.platform.startswith('win') else UnixSocketIPCServer(_ipc_endpoint())
def _ipc_client_for_platform():
    import sys
    return WindowsNamedPipeIPCClient(_ipc_endpoint()) if sys.platform.startswith('win') else UnixSocketIPCClient(_ipc_endpoint())
def _build_base_url_provider(settings: SettingsService) -> ServerDiscovery:
    """Build the production CalDAV Base URL provider with replaceable mDNS discovery."""
    return ServerDiscovery(settings, adapters=[MDNSCalDAVDiscoveryAdapter()])
def _register_builtin_commands(registry,ctx):
    builtins=BuiltinActions(ctx)
    registry.register('today',builtins.today,protected=True); registry.register('next',builtins.next,protected=True); registry.register('done',builtins.done,protected=True); registry.register('edit-due',builtins.edit_due,protected=True)

def build_service_application():
    store=SQLiteStore(_state_dir()/'assistant.sqlite3'); store.migrate()
    cache=SQLiteCacheRepository(store); activity_repo=SQLiteActivityRepository(store); outbox_repo=SQLiteOutboxRepository(store); settings_repo=SQLiteKeyValueRepository(store,'settings'); assistant_state=SQLiteKeyValueRepository(store,'assistant_state'); undo_repo=SQLiteUndoRepository(store)
    settings=SettingsService(settings_repo); session=SessionService(); activity=ActivityService(activity_repo); undo=UndoManager(undo_repo); temporal=TemporalService(TemporalParser())
    base_url_provider=_build_base_url_provider(settings)
    caldav=LibraryCalDAVAdapter(base_url_provider=base_url_provider, credentials=settings.get(CALDAV_CREDENTIALS,None))
    sync=SyncEngine(caldav,cache); tasks=TaskService(caldav,activity,undo); events=EventService(caldav,activity,undo); agenda=AgendaService(tasks,events,AgendaEngine(),NextEngine(),assistant_state); notifications=NotificationService(_notification_adapter_for_platform()); reminders=ReminderService(ReminderEngine(),notifications,temporal,assistant_state,tasks,events); wordpress=WordPressService(WPCLIAdapter(),outbox_repo,activity)
    registry=CommandRegistry(); commands=CommandService(registry); bind_command_registry(registry); hooks=HookRegistry(); ctx=AssistantContext(tasks,events,agenda,reminders,notifications,wordpress,HeadlessUI(),temporal,commands,activity,settings,session); _register_builtin_commands(registry,ctx); extensions=ExtensionManager(commands,hooks,settings); _bind_hook_registrar(hooks); extensions.load_enabled(); dispatcher=RuntimeDispatcher(ctx); background=AssistantService(sync,reminders,wordpress,_ipc_server_for_platform(),dispatcher,PlatformWakeScheduler()); bind_current_context(ctx); return ServiceApplication(ctx,sync,reminders,wordpress,extensions,background)

def build_cli_application():
    runtime=RuntimeClient(_ipc_client_for_platform(),ServiceLauncher().start); tasks=RemoteTasksAPI(runtime); events=RemoteEventsAPI(runtime); agenda=RemoteAgendaAPI(runtime); reminders=RemoteRemindersAPI(runtime); notifications=RemoteNotificationsAPI(runtime); wordpress=RemoteWordPressAPI(runtime); activity=RemoteActivityAPI(runtime); settings=RemoteSettingsAPI(runtime); temporal=TemporalService(TemporalParser()); io=StdConsoleIO(); prompts=PromptKit(io,Menu(io),temporal,tasks,events); session=SessionService(); registry=CommandRegistry(); commands=CommandService(registry); bind_command_registry(registry); hooks=HookRegistry(); ctx=AssistantContext(tasks,events,agenda,reminders,notifications,wordpress,prompts,temporal,commands,activity,settings,session); bind_current_context(ctx); _bind_hook_registrar(hooks); _register_builtin_commands(registry,ctx); extensions=ExtensionManager(commands,hooks,settings); return CLIApplication(ctx,runtime,commands,extensions,io)
def build_application(role='cli'): return build_service_application() if role=='service' else build_cli_application()
