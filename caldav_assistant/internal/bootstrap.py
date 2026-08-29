"""Composition root: concrete infrastructure -> shared Core services."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..api import AssistantContext
from ..api.v1.hooks import _bind_hook_registrar
from ..builtin_extensions.virtual_assistant import install as install_virtual_assistant
from .activity import ActivityService
from .agenda import AgendaEngine, AgendaService, NextEngine
from .caldav import CollectionRoutingCalDAVAdapter, SyncEngine
from .caldav.library_adapter import LibraryCalDAVAdapter
from .caldav.setup import CalDAVSetupService
from .cli.actions import BuiltinActions
from .cli.io import StdConsoleIO
from .commands import CommandRegistry, CommandService
from .commands.decorators import bind_command_registry
from .discovery import ServerDiscovery
from .discovery.adapters import MDNSCalDAVDiscoveryAdapter
from .events import EventService
from .extensions import ExtensionManager, HookRegistry
from .localization import LocaleService
from .notifications import NotificationService
from .notifications.platform_adapters import (
    LinuxNotificationAdapter,
    MacOSNotificationAdapter,
    WindowsNotificationAdapter,
)
from .prompts import Menu, PromptKit
from .reminders import (
    ReminderEngine,
    ReminderRuleRegistry,
    ReminderService,
    bind_reminder_rule_registry,
)
from .runtime.client import RuntimeClient
from .runtime.current_context import bind_current_context
from .runtime.dispatcher import RuntimeDispatcher
from .runtime.headless_ui import HeadlessUI
from .runtime.ipc_platform import (
    UnixSocketIPCClient,
    UnixSocketIPCServer,
    WindowsNamedPipeIPCClient,
    WindowsNamedPipeIPCServer,
)
from .runtime.proxies import (
    RemoteActivityAPI,
    RemoteAgendaAPI,
    RemoteEventsAPI,
    RemoteNotificationsAPI,
    RemoteRemindersAPI,
    RemoteSessionAPI,
    RemoteSettingsAPI,
    RemoteTasksAPI,
    RemoteWordPressAPI,
)
from .runtime.scheduler import PlatformWakeScheduler
from .runtime.service import AssistantService
from .runtime.service_launcher import ServiceLauncher
from .session import CalDAVSessionService
from .settings import PublicSettingsAPI, SettingsService
from .settings.keys import (
    CALDAV_CREDENTIALS,
    CALDAV_EVENT_COLLECTION_URL,
    CALDAV_TASK_COLLECTION_URL,
    CALDAV_WORKLOG_COLLECTION_URL,
    WORDPRESS_PATH,
)
from .storage.sqlite import (
    SQLiteActivityRepository,
    SQLiteCacheRepository,
    SQLiteKeyValueRepository,
    SQLiteOutboxRepository,
    SQLiteStore,
    SQLiteUndoRepository,
)
from .tasks import CompletionLoggingTaskService, TaskCompletionLogService
from .temporal import TemporalParser, TemporalService
from .undo import UndoManager
from .wordpress import WordPressService
from .wordpress.transports import WPCLIAdapter
from .worklog import WorkLogService


_WORK_EVENT_CATEGORY = "caldav-assistant-work"


@dataclass
class ServiceApplication:
    ctx: AssistantContext
    sync: SyncEngine
    reminders: ReminderService
    wordpress: WordPressService
    extensions: ExtensionManager
    background: AssistantService


@dataclass
class CLIApplication:
    ctx: AssistantContext
    runtime: RuntimeClient
    commands: CommandService
    extensions: ExtensionManager
    io: Any


def _state_dir() -> Path:
    return Path.home() / ".caldav-assistant"


def _notification_adapter_for_platform():
    import sys

    if sys.platform.startswith("win"):
        return WindowsNotificationAdapter()
    if sys.platform == "darwin":
        return MacOSNotificationAdapter()
    return LinuxNotificationAdapter()


def _ipc_endpoint() -> str:
    return "caldav-assistant-v1"


def _ipc_server_for_platform():
    import sys

    if sys.platform.startswith("win"):
        return WindowsNamedPipeIPCServer(_ipc_endpoint())
    return UnixSocketIPCServer(_ipc_endpoint())


def _ipc_client_for_platform():
    import sys

    response_timeout = 35.0
    if sys.platform.startswith("win"):
        return WindowsNamedPipeIPCClient(_ipc_endpoint(), timeout=response_timeout)
    return UnixSocketIPCClient(_ipc_endpoint(), timeout=response_timeout)


def _build_base_url_provider(settings: SettingsService) -> ServerDiscovery:
    return ServerDiscovery(settings, adapters=[MDNSCalDAVDiscoveryAdapter()])


def _ordinary_cached_events(loader):
    def load():
        return [
            event
            for event in loader()
            if _WORK_EVENT_CATEGORY
            not in set(getattr(event, "categories", ()) or ())
        ]

    return load


def _register_builtin_commands(registry: CommandRegistry, ctx: AssistantContext) -> None:
    builtins = BuiltinActions(ctx)
    registry.register("today", builtins.today, protected=True)
    registry.register("next", builtins.next, protected=True)
    registry.register("done", builtins.done, protected=True)
    registry.register("edit-due", builtins.edit_due, protected=True)


def build_service_application() -> ServiceApplication:
    store = SQLiteStore(_state_dir() / "assistant.sqlite3")
    store.migrate()

    cache = SQLiteCacheRepository(store)
    activity_repo = SQLiteActivityRepository(store)
    outbox_repo = SQLiteOutboxRepository(store)
    settings_repo = SQLiteKeyValueRepository(store, "settings")
    assistant_state = SQLiteKeyValueRepository(store, "assistant_state")
    undo_repo = SQLiteUndoRepository(store)

    for deprecated_key in ("current_task_uid", "paused_task_uids"):
        try:
            assistant_state.delete(deprecated_key)
        except Exception:
            pass

    settings_service = SettingsService(settings_repo)
    public_settings = PublicSettingsAPI(settings_service)
    activity = ActivityService(activity_repo)
    undo = UndoManager(undo_repo)
    temporal = TemporalService(TemporalParser())

    base_url_provider = _build_base_url_provider(settings_service)
    caldav = LibraryCalDAVAdapter(
        base_url_provider=base_url_provider,
        credentials=settings_service.get(CALDAV_CREDENTIALS, None),
    )
    _caldav_setup = CalDAVSetupService(settings_service, base_url_provider, caldav)
    sync = SyncEngine(caldav, cache)

    routed_caldav = CollectionRoutingCalDAVAdapter(
        caldav,
        task_collection_url=lambda: settings_service.get(CALDAV_TASK_COLLECTION_URL, None),
        event_collection_url=lambda: settings_service.get(CALDAV_EVENT_COLLECTION_URL, None),
    )

    worklog = WorkLogService(
        routed_caldav,
        lambda: settings_service.get(CALDAV_WORKLOG_COLLECTION_URL, None),
    )

    wordpress = WordPressService(
        WPCLIAdapter(settings_service.get(WORDPRESS_PATH, None)),
        outbox_repo,
        activity,
    )
    completion_log = TaskCompletionLogService(worklog, wordpress)

    session = CalDAVSessionService(worklog)
    tasks = CompletionLoggingTaskService(
        routed_caldav,
        activity,
        undo,
        session,
        worklog=worklog,
        completion_log=completion_log,
    )
    session.bind_tasks(tasks)

    events = EventService(routed_caldav, activity, undo)
    undo.bind(tasks=tasks, events=events)
    agenda = AgendaService(
        tasks,
        events,
        AgendaEngine(),
        NextEngine(),
        assistant_state,
        session=session,
    )
    notifications = NotificationService(_notification_adapter_for_platform())
    reminder_rules = ReminderRuleRegistry()
    bind_reminder_rule_registry(reminder_rules)
    reminders = ReminderService(
        ReminderEngine(),
        notifications,
        temporal,
        assistant_state,
        sync.cached_tasks,
        _ordinary_cached_events(sync.cached_events),
        reminder_rules,
    )

    registry = CommandRegistry()
    commands = CommandService(registry)
    bind_command_registry(registry)
    hooks = HookRegistry()
    ctx = AssistantContext(
        tasks,
        events,
        agenda,
        reminders,
        notifications,
        wordpress,
        HeadlessUI(),
        temporal,
        commands,
        activity,
        public_settings,
        session,
    )
    _register_builtin_commands(registry, ctx)
    install_virtual_assistant(ctx, reminder_rules=reminder_rules)

    extensions = ExtensionManager(commands, hooks, settings_service)
    _bind_hook_registrar(hooks)
    bind_current_context(ctx)
    extensions.load_enabled()

    dispatcher = RuntimeDispatcher(ctx)
    dispatcher.register_internal("caldav.status", _caldav_setup.status)
    dispatcher.register_internal("caldav.set_base_url", _caldav_setup.set_base_url)
    dispatcher.register_internal("caldav.set_credentials", _caldav_setup.set_credentials)
    dispatcher.register_internal("caldav.clear_credentials", _caldav_setup.clear_credentials)
    dispatcher.register_internal("caldav.test", _caldav_setup.test_connection)
    dispatcher.register_internal("caldav.collections", _caldav_setup.collections)
    dispatcher.register_internal("undo.last", undo.undo_last)
    background = AssistantService(
        sync,
        reminders,
        wordpress,
        _ipc_server_for_platform(),
        dispatcher,
        PlatformWakeScheduler(),
    )
    return ServiceApplication(
        ctx,
        sync,
        reminders,
        wordpress,
        extensions,
        background,
    )


def build_cli_application() -> CLIApplication:
    runtime = RuntimeClient(
        _ipc_client_for_platform(),
        ServiceLauncher().start,
        request_timeout=30.0,
    )
    tasks = RemoteTasksAPI(runtime)
    events = RemoteEventsAPI(runtime)
    agenda = RemoteAgendaAPI(runtime)
    reminders = RemoteRemindersAPI(runtime)
    notifications = RemoteNotificationsAPI(runtime)
    wordpress = RemoteWordPressAPI(runtime)
    activity = RemoteActivityAPI(runtime)
    settings = RemoteSettingsAPI(runtime)
    session = RemoteSessionAPI(runtime)
    temporal = TemporalService(TemporalParser())
    io = StdConsoleIO()
    locale = LocaleService(settings)
    menu = Menu(io, locale=locale)
    prompts = PromptKit(
        io,
        menu,
        temporal,
        tasks,
        events,
        locale=locale,
    )
    registry = CommandRegistry()
    commands = CommandService(registry)
    bind_command_registry(registry)
    hooks = HookRegistry()
    ctx = AssistantContext(
        tasks,
        events,
        agenda,
        reminders,
        notifications,
        wordpress,
        prompts,
        temporal,
        commands,
        activity,
        settings,
        session,
    )
    bind_current_context(ctx)
    _bind_hook_registrar(hooks)
    _register_builtin_commands(registry, ctx)
    local_rule_registry = ReminderRuleRegistry()
    install_virtual_assistant(ctx, reminder_rules=local_rule_registry)
    extensions = ExtensionManager(commands, hooks, settings)
    return CLIApplication(ctx, runtime, commands, extensions, io)


def build_application(role: str = "cli"):
    return build_service_application() if role == "service" else build_cli_application()
