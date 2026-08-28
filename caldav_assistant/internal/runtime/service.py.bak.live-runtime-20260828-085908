"""Authoritative lightweight Assistant background service.

Orchestration only: Local IPC, low-frequency maintenance, Reminder wakeups.
Task/Event business logic remains in Core Services behind RuntimeDispatcher.
"""
from __future__ import annotations
from datetime import datetime, timezone
from threading import Event, RLock, Thread
from typing import Any
import os, signal
from .ipc import IPCAlreadyRunningError
from .scheduler import PlatformWakeScheduler

class AssistantService:
    def __init__(self, sync: Any, reminders: Any, wordpress: Any, ipc_server: Any, dispatcher: Any, scheduler: Any|None=None, *, sync_interval: float=60.0, wordpress_interval: float=60.0, max_idle: float=30.0) -> None:
        self.sync=sync; self.reminders=reminders; self.wordpress=wordpress; self.ipc_server=ipc_server; self.dispatcher=dispatcher
        self.scheduler=scheduler or PlatformWakeScheduler(); self.sync_interval=float(sync_interval); self.wordpress_interval=float(wordpress_interval); self.max_idle=float(max_idle)
        self._stop_event=Event(); self._running=Event(); self._lock=RLock(); self._started_at=None; self._last_success={}; self._last_errors={}; self._maintenance_thread=None
    @property
    def running(self)->bool: return self._running.is_set()
    def _run_one(self, label: str, target: Any, *args: Any, **kwargs: Any) -> None:
        if not callable(target): return
        try:
            target(*args,**kwargs)
            with self._lock: self._last_success[label]=datetime.now(timezone.utc).isoformat(); self._last_errors.pop(label,None)
        except Exception as exc:
            with self._lock: self._last_errors[label]=f"{type(exc).__name__}: {exc}"
    def run_maintenance_once(self)->None:
        incremental=getattr(self.sync,"incremental_sync",None) or getattr(self.sync,"refresh",None)
        self._run_one("sync.incremental",incremental)
        self._run_one("reminders.process_due",getattr(self.reminders,"process_due",None))
        self._run_one("wordpress.flush",getattr(self.wordpress,"flush",None))
    def _maintenance_loop(self)->None:
        next_sync=0.0; next_wordpress=0.0
        while not self._stop_event.is_set():
            now=self.scheduler.monotonic()
            if now>=next_sync:
                self._run_one("sync.incremental",getattr(self.sync,"incremental_sync",None) or getattr(self.sync,"refresh",None)); next_sync=now+self.sync_interval
            self._run_one("reminders.process_due",getattr(self.reminders,"process_due",None))
            if now>=next_wordpress:
                self._run_one("wordpress.flush",getattr(self.wordpress,"flush",None)); next_wordpress=now+self.wordpress_interval
            reminder_delay=self.scheduler.reminder_delay(self.reminders,max_delay=self.max_idle)
            delay=min(self.max_idle,max(0.0,next_sync-now),max(0.0,next_wordpress-now),reminder_delay)
            if delay<=0: delay=0.05
            self.scheduler.wait(delay,self._stop_event)
    def _handle_request(self, method: str, payload: dict[str,Any]|None=None)->Any:
        if method=="runtime.ping": return {"status":"ok","pid":os.getpid()}
        if method=="runtime.status": return self.status()
        return self.dispatcher.handle(method,payload or {})
    def status(self)->dict[str,Any]:
        with self._lock:
            return {"status":"running" if self.running else "stopped","pid":os.getpid(),"started_at":self._started_at.isoformat() if self._started_at else None,"last_success":dict(self._last_success),"last_errors":dict(self._last_errors)}
    def run_forever(self)->None:
        if self._running.is_set(): raise RuntimeError("AssistantService is already running")
        self._stop_event.clear(); self._running.set(); self._started_at=datetime.now(timezone.utc)
        self._maintenance_thread=Thread(target=self._maintenance_loop,name="caldav-assistant-maintenance",daemon=True); self._maintenance_thread.start()
        try: self.ipc_server.serve_forever(self._handle_request,self._stop_event)
        finally:
            self._stop_event.set(); self._running.clear(); close=getattr(self.ipc_server,"close",None)
            if callable(close): close()
    start=run_forever
    def stop(self)->None:
        self._stop_event.set(); close=getattr(self.ipc_server,"close",None)
        if callable(close): close()

def main()->int:
    from ..bootstrap import build_service_application
    application=build_service_application(); service=application.background
    def request_stop(signum:int,frame:Any)->None: service.stop()
    for name in ("SIGTERM","SIGINT"):
        sig=getattr(signal,name,None)
        if sig is not None:
            try: signal.signal(sig,request_stop)
            except (ValueError,OSError): pass
    try: service.run_forever()
    except IPCAlreadyRunningError: return 0
    except KeyboardInterrupt: service.stop(); return 130
    return 0

if __name__=="__main__": raise SystemExit(main())
__all__=["AssistantService","main"]
