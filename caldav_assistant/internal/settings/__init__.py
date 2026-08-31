from .keys import *
from .schema import SettingSpec,SettingsSchema,DEFAULT_SETTINGS_SCHEMA
from .service import SettingsService
from .public import PublicSettingsAPI
__all__=[
    "SettingsService",
    "PublicSettingsAPI",
    "SettingSpec",
    "SettingsSchema",
    "DEFAULT_SETTINGS_SCHEMA",
    "CALDAV_BASE_URL",
    "CALDAV_CREDENTIALS",
    "CALDAV_TASK_COLLECTION_URL",
    "CALDAV_EVENT_COLLECTION_URL",
    "CALDAV_WORKLOG_COLLECTION_URL",
    "UI_LOCALE",
    "COMMAND_LANGUAGE",
    "NOTIFICATIONS_ENABLED",
    "WORDPRESS_ENABLED",
    "WORDPRESS_PATH",
    "WORDPRESS_WORKLOG_STYLE",
    "WORDPRESS_WORKLOG_TEMPLATE",
    "EXTENSIONS_ENABLED",
    "EXPERIMENTAL_FAST_QUERY_CACHE",
    "AGENDA_UPCOMING_HOURS",
]
