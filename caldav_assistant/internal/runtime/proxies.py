class _Proxy:
    prefix=''
    def __init__(self,runtime): self.runtime=runtime
    def _call(self,name,**kwargs): return self.runtime.call(f'{self.prefix}.{name}',**kwargs)
class RemoteTasksAPI(_Proxy):
    prefix='tasks'
    def list(self,**k): return self._call('list',**k)
    def find(self,query,**k): return self._call('find',query=query,**k)
    def get(self,task): return self._call('get',task=task)
    def create(self,summary,**k): return self._call('create',summary=summary,**k)
    def update(self,task,**k): return self._call('update',task=task,**k)
    def complete(self,task): return self._call('complete',task=task)
    def start(self,task): return self._call('start',task=task)
    def pause(self,task): return self._call('pause',task=task)
    def resume(self,task): return self._call('resume',task=task)
    def delete(self,task): return self._call('delete',task=task)
class RemoteEventsAPI(_Proxy):
    prefix='events'
    def list(self,**k): return self._call('list',**k)
    def find(self,query,**k): return self._call('find',query=query,**k)
    def get(self,event): return self._call('get',event=event)
    def create(self,summary,**k): return self._call('create',summary=summary,**k)
    def update(self,event,**k): return self._call('update',event=event,**k)
    def delete(self,event): return self._call('delete',event=event)
class RemoteAgendaAPI(_Proxy):
    prefix='agenda'
    def today(self): return self._call('today')
    def range(self,**k): return self._call('range',**k)
    def next(self,**k): return self._call('next',**k)
    def overdue(self): return self._call('overdue')
class RemoteRemindersAPI(_Proxy):
    prefix='reminders'
    def list(self,**k): return self._call('list',**k)
    def create(self,title,when,**k): return self._call('create',title=title,when=when,**k)
    def snooze(self,reminder,until): return self._call('snooze',reminder=reminder,until=until)
    def cancel(self,reminder): return self._call('cancel',reminder=reminder)
class RemoteNotificationsAPI(_Proxy):
    prefix='notifications'
    def send(self,title,body='',actions=None): return self._call('send',title=title,body=body,actions=actions)
class RemoteWordPressAPI(_Proxy):
    prefix='wordpress'
    def log(self,text,**k): return self._call('log',text=text,**k)
    def create_post(self,**k): return self._call('create_post',**k)
    def update_post(self,**k): return self._call('update_post',**k)
    def pending(self): return self._call('pending')
class RemoteActivityAPI(_Proxy):
    prefix='activity'
    def today(self): return self._call('today')
    def for_task(self,task): return self._call('for_task',task=task)
    def record(self,action,object_id=None,**metadata): return self._call('record',action=action,object_id=object_id,**metadata)
class RemoteSettingsAPI(_Proxy):
    prefix='settings'
    def get(self,key,default=None): return self._call('get',key=key,default=default)
    def set(self,key,value): return self._call('set',key=key,value=value)
