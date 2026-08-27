from pathlib import Path
import pytest
from caldav_assistant.internal.localization import DirectoryLocaleProvider,LocaleService,UI_LOCALE_KEY,normalize_locale
class MemorySettings:
    def __init__(self):self.values={}
    def get(self,key,default=None):return self.values.get(key,default)
    def set(self,key,value):self.values[key]=value
class FailingSettings:
    def get(self,key,default=None):raise OSError("offline")
def test_normalization():
    assert normalize_locale("en_US.UTF-8")=="en";assert normalize_locale("zh_CN.UTF-8")=="zh-CN";assert normalize_locale("zh-Hans")=="zh-CN"
def test_builtin_locales_and_persistence():
    settings=MemorySettings(); service=LocaleService(settings); assert service.t("prompt.choose_task")=="Choose task";assert service.set_locale("zh_CN")=="zh-CN";assert settings.values[UI_LOCALE_KEY]=="zh-CN";assert service.t("prompt.choose_task")=="选择任务"
def test_bad_pack_is_isolated(tmp_path):
    (tmp_path/"bad.toml").write_text('[locale]\ncode="fr"\n'); provider=DirectoryLocaleProvider(tmp_path);assert provider.available()==();assert provider.errors
def test_failing_settings_keeps_english():assert LocaleService(FailingSettings()).t("cli.banner")=="CalDAV Assistant"
def test_safe_missing_placeholder():assert LocaleService(MemorySettings()).t("missing",default="Hello {name}")=="Hello {name}"
