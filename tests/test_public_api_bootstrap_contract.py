from __future__ import annotations

import inspect

from caldav_assistant.internal import bootstrap


def test_service_composition_root_binds_easy_api_context():
    source = inspect.getsource(bootstrap.build_service_application)
    assert "bind_current_context(ctx)" in source


def test_cli_composition_root_binds_easy_api_context():
    source = inspect.getsource(bootstrap.build_cli_application)
    assert "bind_current_context(ctx)" in source
