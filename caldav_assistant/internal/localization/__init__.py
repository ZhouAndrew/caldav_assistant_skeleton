"""Internal UI-localization subsystem."""
from .codes import normalize_locale
from .providers import BuiltinLocaleProvider,DirectoryLocaleProvider,LocaleCatalog,LocaleInfo,LocaleProvider
from .service import DEFAULT_LOCALE,UI_LOCALE_KEY,LocaleService
__all__=["DEFAULT_LOCALE","UI_LOCALE_KEY","normalize_locale","LocaleInfo","LocaleCatalog","LocaleProvider","BuiltinLocaleProvider","DirectoryLocaleProvider","LocaleService"]
