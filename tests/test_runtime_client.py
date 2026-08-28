from __future__ import annotations
import pytest
from caldav_assistant.internal.runtime.client import RuntimeClient
from caldav_assistant.internal.runtime.ipc import IPCRemoteError, IPCUnavailableError

def test_call_and_request_alias():
    class IPC:
        def call(self, method, payload): return method, payload
    client=RuntimeClient(IPC())
    assert client.call("x.y",value=3)==("x.y",{"value":3})
    assert client.request("x.y",{"value":4})==("x.y",{"value":4})

def test_auto_starts_once_then_retries():
    state={"ready":False,"launches":0}
    class IPC:
        def call(self, method, payload):
            if not state["ready"]: raise IPCUnavailableError("offline")
            return {"status":"ok"} if method=="runtime.ping" else "done"
    def launch(): state["launches"]+=1; state["ready"]=True
    client=RuntimeClient(IPC(),launch,startup_timeout=.5,poll_interval=.01)
    assert client.call("tasks.list")=="done"; assert state["launches"]==1


def test_runtime_client_rebinds_nested_agenda_task_objects():
    from caldav_assistant.api import Agenda, AgendaItem, Task

    class IPC:
        def call(self, method, payload):
            return Agenda([AgendaItem(Task(id="t1", summary="Nested"), kind="task")])

    class TaskBinder:
        pass

    binder = TaskBinder()
    client = RuntimeClient(IPC())
    client.bind_domain("task", binder)

    agenda = client._execute("agenda.today", {})
    assert agenda.items[0].value._service is binder
