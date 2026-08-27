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
    public=make();assert public.get(UI_LOCALE)=="en";assert public.set(UI_LOCALE,"zh-cn")=="zh-CN";assert public.get(NOTIFICATIONS_ENABLED) is True;assert public.set(NOTIFICATIONS_ENABLED,"off") is False
def test_credentials_are_write_only():
    public=make();public.set(CALDAV_CREDENTIALS,{"username":"a","password":"b"})
    with pytest.raises(ValidationError):public.get(CALDAV_CREDENTIALS)
def test_extension_state_registered():
    public=make();assert public.get(EXTENSIONS_ENABLED)=={};assert public.set(EXTENSIONS_ENABLED,{"school":True})=={"school":True}
def test_categories_shape():assert DEFAULT_SETTINGS_SCHEMA.categories()==("Language","CalDAV","Notifications","WordPress","Commands","Extensions")
