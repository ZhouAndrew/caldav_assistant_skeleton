import pytest
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.settings import *
class Repo:
    def __init__(self):self.values={}
    def get(self,key,default=None):return self.values.get(key,default)
    def set(self,key,value):self.values[key]=value
    def delete(self,key):self.values.pop(key,None)
def make():return PublicSettingsAPI(SettingsService(Repo()))
def test_defaults_and_validation():
    public=make();assert public.get(UI_LOCALE)=="en";assert public.set(UI_LOCALE,"zh-cn")=="zh-CN";assert public.get(NOTIFICATIONS_ENABLED) is False;assert public.set(NOTIFICATIONS_ENABLED,"off") is False
def test_reminder_alert_defaults_are_readable_and_validated():
    public=make()
    assert public.get(NOTIFICATION_SOUND_ENABLED) is True
    assert public.get(TERMINAL_BELL_ENABLED) is True
    assert public.get(TERMINAL_BELL_REPEAT_COUNT)==3
    assert public.get(TERMINAL_BELL_INTERVAL_MS)==400
    assert public.set(TERMINAL_BELL_REPEAT_COUNT,"5")==5
    assert public.set(TERMINAL_BELL_INTERVAL_MS,"650")==650
    with pytest.raises(ValidationError):public.set(TERMINAL_BELL_REPEAT_COUNT,0)
    with pytest.raises(ValidationError):public.set(TERMINAL_BELL_REPEAT_COUNT,11)
    with pytest.raises(ValidationError):public.set(TERMINAL_BELL_INTERVAL_MS,99)
    with pytest.raises(ValidationError):public.set(TERMINAL_BELL_INTERVAL_MS,2001)
def test_credentials_are_write_only():
    public=make();public.set(CALDAV_CREDENTIALS,{"username":"a","password":"b"})
    with pytest.raises(ValidationError):public.get(CALDAV_CREDENTIALS)
def test_extension_state_registered():
    public=make();assert public.get(EXTENSIONS_ENABLED)=={};assert public.set(EXTENSIONS_ENABLED,{"school":True})=={"school":True}
def test_categories_shape():assert DEFAULT_SETTINGS_SCHEMA.categories()==("Language","CalDAV","Tasks","Notifications","WordPress","Commands","Extensions","Agenda","Experimental")
def test_task_default_view_is_public_and_validated():
    public=make();assert public.get(TASK_DEFAULT_VIEW)=="incomplete";assert public.set(TASK_DEFAULT_VIEW,"TODAY")=="today"
    with pytest.raises(ValidationError):public.set(TASK_DEFAULT_VIEW,"everything")

def test_upcoming_window_is_public_and_validated():
    public=make();assert public.get(AGENDA_UPCOMING_HOURS)==24;assert public.set(AGENDA_UPCOMING_HOURS,"36")==36
    with pytest.raises(ValidationError):public.set(AGENDA_UPCOMING_HOURS,0)
def test_wordpress_worklog_defaults_to_compact_and_is_user_customizable():
    public=make()
    assert public.get(WORDPRESS_WORKLOG_STYLE)=="compact"
    assert public.get(WORDPRESS_WORKLOG_TEMPLATE)=="{start}-{end} {task}"
    assert public.set(WORDPRESS_WORKLOG_STYLE,"CUSTOM")=="custom"
    assert public.set(WORDPRESS_WORKLOG_TEMPLATE,"{task} {duration_minutes}m")=="{task} {duration_minutes}m"
    with pytest.raises(ValidationError):public.set(WORDPRESS_WORKLOG_STYLE,"noisy")
    with pytest.raises(ValidationError):public.set(WORDPRESS_WORKLOG_TEMPLATE,"{unknown}")

def test_wordpress_transport_settings_are_validated_and_secret_is_write_only():
    public=make()
    assert public.get(WORDPRESS_TRANSPORT)=="auto"
    assert public.set(WORDPRESS_TRANSPORT,"REST")=="application-password"
    assert public.set(WORDPRESS_BASE_URL,"https://andrew.local/")=="https://andrew.local"
    assert public.set(WORDPRESS_USERNAME,"wp_user")=="wp_user"
    assert public.set(WORDPRESS_APPLICATION_PASSWORD_FILE,"/tmp/wp-pass")=="/tmp/wp-pass"
    public.set(WORDPRESS_APPLICATION_PASSWORD,"abcd efgh")
    with pytest.raises(ValidationError):public.get(WORDPRESS_APPLICATION_PASSWORD)
    with pytest.raises(ValidationError):public.set(WORDPRESS_TRANSPORT,"magic")
    with pytest.raises(ValidationError):public.set(WORDPRESS_BASE_URL,"andrew.local")
