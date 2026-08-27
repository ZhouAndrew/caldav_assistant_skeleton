from caldav_assistant.internal.extensions import HookRegistry

def test_hook_failure_is_isolated_and_later_hook_still_runs():
    hooks=HookRegistry(); calls=[]
    def broken(value): calls.append(("broken",value)); raise RuntimeError("boom")
    def good(value): calls.append(("good",value)); return value+1
    hooks.register("task.completed",broken,owner="bad"); hooks.register("task.completed",good,owner="good")
    assert hooks.emit("task.completed",4)==[5]
    assert calls==[("broken",4),("good",4)]
    failures=hooks.failures(); assert len(failures)==1; assert failures[0].owner=="bad"

def test_unregister_owner_removes_only_that_extensions_hooks():
    hooks=HookRegistry(); a=lambda:"a"; b=lambda:"b"
    hooks.register("task.completed",a,owner="alpha"); hooks.register("task.completed",b,owner="beta")
    assert len(hooks.unregister_owner("alpha"))==1
    assert hooks.emit("task.completed")==["b"]
