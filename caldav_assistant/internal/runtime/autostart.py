"""User-level login autostart management for the background Assistant Service."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable
import os, plistlib, shlex, subprocess, sys

class AutostartManager:
    def __init__(self, *, python: str|None=None, runner: Callable[...,Any]=subprocess.run) -> None:
        self.python=python or sys.executable; self._runner=runner
    @property
    def command(self)->list[str]: return [self.python,"-m","caldav_assistant.internal.runtime.service"]
    @staticmethod
    def _systemd_path()->Path: return Path.home()/".config/systemd/user/caldav-assistant.service"
    @staticmethod
    def _launchd_path()->Path: return Path.home()/"Library/LaunchAgents/org.caldav-assistant.service.plist"
    def enable(self)->None:
        if sys.platform.startswith("linux"):
            p=self._systemd_path(); p.parent.mkdir(parents=True,exist_ok=True)
            cmd=" ".join(shlex.quote(x) for x in self.command)
            p.write_text(f"[Unit]\nDescription=CalDAV Assistant\n\n[Service]\nExecStart={cmd}\nRestart=on-failure\n\n[Install]\nWantedBy=default.target\n")
            self._run(["systemctl","--user","daemon-reload"]); self._run(["systemctl","--user","enable","--now",p.name]); return
        if sys.platform=="darwin":
            p=self._launchd_path(); p.parent.mkdir(parents=True,exist_ok=True)
            with p.open("wb") as f: plistlib.dump({"Label":"org.caldav-assistant.service","ProgramArguments":self.command,"RunAtLoad":True,"KeepAlive":True},f)
            self._run(["launchctl","bootstrap",f"gui/{os.getuid()}",str(p)]); return
        if sys.platform.startswith("win"):
            cmd=subprocess.list2cmdline(self.command); self._run(["schtasks","/Create","/F","/SC","ONLOGON","/TN","CalDAV Assistant","/TR",cmd]); return
        raise RuntimeError(f"Autostart is unsupported on platform: {sys.platform}")
    def _run(self,args:list[str]): return self._runner(args,check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def disable(self, *, stop: bool=True)->None:
        if sys.platform.startswith("linux"):
            p=self._systemd_path();
            if stop: self._run(["systemctl","--user","disable","--now",p.name])
            try: p.unlink()
            except FileNotFoundError: pass
            self._run(["systemctl","--user","daemon-reload"]); return
        if sys.platform=="darwin":
            p=self._launchd_path()
            if stop and p.exists(): self._run(["launchctl","bootout",f"gui/{os.getuid()}",str(p)])
            try: p.unlink()
            except FileNotFoundError: pass
            return
        if sys.platform.startswith("win"):
            if stop: self._run(["schtasks","/End","/TN","CalDAV Assistant"])
            self._run(["schtasks","/Delete","/F","/TN","CalDAV Assistant"]); return
        raise RuntimeError(f"Autostart is unsupported on platform: {sys.platform}")
    def is_enabled(self)->bool:
        if sys.platform.startswith("linux"): return self._systemd_path().is_file()
        if sys.platform=="darwin": return self._launchd_path().is_file()
        if sys.platform.startswith("win"):
            result=self._runner(["schtasks","/Query","/TN","CalDAV Assistant"],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); return getattr(result,"returncode",1)==0
        return False

__all__=["AutostartManager"]
