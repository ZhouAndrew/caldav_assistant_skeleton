from caldav_assistant.internal.runtime.service_launcher import ServiceLauncher

def test_launcher_uses_current_python_module_entry_without_shell(tmp_path):
    calls=[]
    class Process: pid=123
    def popen(command,**kwargs): calls.append((command,kwargs)); return Process()
    launcher=ServiceLauncher(python="/example/python",popen=popen,state_dir=tmp_path)
    assert launcher.start().pid==123
    command,kwargs=calls[0]
    assert command==[
        "/example/python",
        "-m",
        "caldav_assistant.internal.runtime.versioned_observable_service",
    ]
    assert "shell" not in kwargs


def test_launcher_runtime_log_is_private_on_posix(tmp_path):
    import os
    import stat
    import pytest

    if os.name == "nt":
        pytest.skip("POSIX permission bits")

    class Process:
        pid = 123

    launcher = ServiceLauncher(
        python="/example/python",
        popen=lambda command, **kwargs: Process(),
        state_dir=tmp_path / "runtime",
    )
    launcher.start()
    assert stat.S_IMODE(launcher.log_path.stat().st_mode) & 0o077 == 0
