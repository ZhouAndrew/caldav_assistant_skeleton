from types import SimpleNamespace

from caldav_assistant.internal.cli import versioned_entrypoint
from caldav_assistant.internal.web.server import WebActions, _auto_collection_roles


def _collections():
    return [
        {
            "name": "Tasks",
            "url": "http://server.local/tasks/",
            "supported_components": ["VTODO", "VEVENT"],
        },
        {
            "name": "Assistant Work",
            "url": "http://server.local/work/",
            "supported_components": ["VEVENT"],
        },
    ]


def test_collection_roles_keep_tasks_and_work_separate_when_names_are_clear():
    roles = _auto_collection_roles(_collections())

    assert roles == {
        "task": "http://server.local/tasks/",
        "event": "http://server.local/tasks/",
        "worklog": "http://server.local/work/",
    }


class FakeSettings:
    def __init__(self):
        self.base_url = None
        self.credentials = None
        self.values = {}
        self.refreshes = 0

    def caldav_status(self):
        return {
            "base_url": self.base_url,
            "base_url_configured": bool(self.base_url),
            "base_url_source": "saved" if self.base_url else None,
            "discovered_candidates": [],
            "credentials_configured": self.credentials is not None,
        }

    def set_caldav_base_url(self, value):
        self.base_url = value
        return self.caldav_status()

    def set_caldav_credentials(self, username, password):
        self.credentials = {"username": username, "password": password}
        return self.caldav_status()

    def clear_caldav_credentials(self):
        self.credentials = None
        return self.caldav_status()

    def test_caldav_connection(self):
        return {
            "ok": True,
            "base_url": self.base_url,
            "collection_count": 2,
            "collections": _collections(),
        }

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value

    def _experimental_cache_refresh(self):
        self.refreshes += 1
        return {"tasks": 1, "events": 1}


def test_first_run_connect_normalizes_local_host_and_finishes_in_one_action():
    settings = FakeSettings()
    app = SimpleNamespace(ctx=SimpleNamespace(settings=settings))
    actions = WebActions(app)

    result = actions.connect({"base_url": "andrew.local:5232"})

    assert settings.base_url == "http://andrew.local:5232"
    assert result["ready"] is True
    assert result["connection_ok"] is True
    assert result["roles"]["task"].endswith("/tasks/")
    assert result["roles"]["worklog"].endswith("/work/")
    assert settings.refreshes == 1


def test_web_subcommand_routes_before_cli_application_is_built(monkeypatch):
    from caldav_assistant.internal.web import server as web_server

    seen = {}

    def fake_main(argv=None):
        seen["argv"] = list(argv or ())
        return 17

    monkeypatch.setattr(web_server, "main", fake_main)

    assert (
        versioned_entrypoint.run_cli(
            ["web", "--no-open", "--port", "0"],
            app=object(),
        )
        == 17
    )
    assert seen["argv"] == ["--no-open", "--port", "0"]
