from __future__ import annotations

import pytest

from caldav_assistant.api import UnavailableError
from caldav_assistant.internal.runtime.current_context import (
    bind_current_context,
    clear_current_context,
    get_current_context,
)


def teardown_function():
    clear_current_context()


def test_unbound_easy_context_uses_stable_public_error():
    clear_current_context()
    with pytest.raises(UnavailableError):
        get_current_context()


def test_context_binding_is_process_local_and_explicit():
    first = object()
    second = object()

    assert bind_current_context(first) is None
    assert get_current_context() is first

    assert bind_current_context(second) is first
    assert get_current_context() is second

    assert clear_current_context() is second
    with pytest.raises(UnavailableError):
        get_current_context()
