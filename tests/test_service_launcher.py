from caldav_assistant.internal.runtime.service_launcher import ServiceLauncher

def test_launcher_uses_current_python_module_entry_without_shell(tmp_path):
    calls=[]
    class Process: pid=123
    def popen(command,**kwargs): calls.append((command,kwargs)); return Process()
    launcher=ServiceLauncher(python="/example/python",popen=popen,state_dir=tmp_path)
    assert launcher.start().pid==123
    command,kwargs=calls[0]
    assert command==["/example/python","-m","caldav_assistant.internal.runtime.service"]
    assert "shell" not in kwargs
