from ...api import Event
from ...api.v1.errors import NotFoundError
class EventService:
    def __init__(self, adapter, activity=None, undo=None): self.adapter=adapter; self.activity=activity; self.undo=undo
    def list(self, **filters): return list(self.adapter.list_events(**filters)) if hasattr(self.adapter,'list_events') else []
    def find(self, query, **filters):
        items=[e for e in self.list(**filters) if query.lower() in e.summary.lower()]
        if not items: raise NotFoundError(query)
        return items[0] if len(items)==1 else items
    def get(self,event): return event if isinstance(event,Event) else self.adapter.get_event(event)
    def create(self,summary,**fields):
        event=summary if isinstance(summary,Event) else Event(summary=summary,**fields); event._service=self
        return self.adapter.create_event(event) if hasattr(self.adapter,'create_event') else event
    def update(self,event,**changes):
        obj=self.get(event); [setattr(obj,k,v) for k,v in changes.items() if hasattr(obj,k)]
        return self.adapter.update_event(obj.id,changes) if hasattr(self.adapter,'update_event') else obj
    def delete(self,event):
        obj=self.get(event); return self.adapter.delete_event(obj.id) if hasattr(self.adapter,'delete_event') else None
