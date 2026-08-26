from ...api import Reminder
import uuid
class ReminderService:
    def __init__(self,engine,notifications,temporal,state,tasks=None,events=None): self.engine=engine; self.notifications=notifications; self.temporal=temporal; self.state=state; self._items={}
    def list(self,**filters): return list(self._items.values())
    def create(self,title,when,**metadata):
        if isinstance(when,str): when=self.temporal.parse_datetime(when,bias='future')
        r=Reminder(str(uuid.uuid4()),title,when,metadata); self._items[r.id]=r; return r
    def snooze(self,reminder,until):
        r=self._items.get(reminder if isinstance(reminder,str) else reminder.id, reminder); r.when=self.temporal.parse_datetime(until,bias='future') if isinstance(until,str) else until; return r
    def cancel(self,reminder): return self._items.pop(reminder if isinstance(reminder,str) else reminder.id,None)
