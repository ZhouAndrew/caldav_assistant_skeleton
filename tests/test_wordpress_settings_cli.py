from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.settings import PublicSettingsAPI, SettingsService
from caldav_assistant.internal.settings.cli import SettingsActions
from caldav_assistant.internal.settings.keys import WORDPRESS_APPLICATION_PASSWORD


class Repo:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class UI:
    def __init__(self, secret):
        self.secret = secret
        self.messages = []

    def ask_secret(self, _prompt):
        return self.secret

    def show(self, value):
        self.messages.append(str(value))


class WordPressProbe:
    def __init__(self, result=True):
        self.result = result
        self.calls = 0

    def _test_connection(self):
        self.calls += 1
        return self.result


def make(secret="abcd efgh"):
    repo = Repo()
    public = PublicSettingsAPI(SettingsService(repo))
    ui = UI(secret)
    wordpress = WordPressProbe()
    ctx = SimpleNamespace(settings=public, ui=ui, wordpress=wordpress)
    return SettingsActions(ctx), repo, ui, wordpress, public


def test_application_password_secure_setup_never_displays_or_publicly_reads_secret():
    actions, repo, ui, _wordpress, public = make("abcd efgh ijkl")

    assert actions._set_wordpress_application_password() is True
    assert repo.values[WORDPRESS_APPLICATION_PASSWORD] == "abcd efgh ijkl"
    assert all("abcd" not in message for message in ui.messages)
    assert any("configured" in message for message in ui.messages)

    with pytest.raises(ValidationError):
        public.get(WORDPRESS_APPLICATION_PASSWORD)


def test_application_password_is_rejected_on_command_line_setting_path():
    actions, repo, _ui, _wordpress, _public = make()

    with pytest.raises(ValidationError):
        actions.set_setting(WORDPRESS_APPLICATION_PASSWORD, "must-not-be-on-command-line")
    assert WORDPRESS_APPLICATION_PASSWORD not in repo.values


def test_wordpress_connection_test_uses_runtime_wordpress_probe():
    actions, _repo, ui, wordpress, _public = make()

    assert actions._test_wordpress_connection() is True
    assert wordpress.calls == 1
    assert ui.messages[-1] == "✓ WordPress connection succeeded."


def test_wordpress_connection_failure_is_explicit():
    actions, _repo, _ui, wordpress, _public = make()
    wordpress.result = False

    with pytest.raises(ValidationError, match="WordPress connection failed"):
        actions._test_wordpress_connection()
