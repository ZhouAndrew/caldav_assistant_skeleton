"""On-demand background service launcher used by RuntimeClient."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable
import os, subprocess, sys
from .ipc import runtime_state_dir

class ServiceLauncher:
    def __init__(self, *, python: str | None=None, popen: Callable[...,Any]=subprocess.Popen, state_dir: str|Path|None=None) -> None:
        self.python=python or sys.executable; self._popen=popen; self.state_dir=runtime_state_dir(state_dir)
    @property
    def log_path(self)->Path: return self.state_dir/"service.log"
    def start(self)->Any:
        command=[self.python,"-m","caldav_assistant.internal.runtime.service"]
        self.state_dir.mkdir(parents=True,exist_ok=True)
        log=open(self.log_path,"ab",buffering=0)
        kwargs={"stdin":subprocess.DEVNULL,"stdout":log,"stderr":subprocess.STDOUT,"close_fds":os.name!="nt","cwd":str(Path.home())}
        if os.name=="nt":
            flags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)|getattr(subprocess,"DETACHED_PROCESS",0); kwargs["creationflags"]=flags
        else: kwargs["start_new_session"]=True
        try: return self._popen(command,**kwargs)
        finally: log.close()

__all__=["ServiceLauncher"]
