from datetime import datetime
from ...api import Activity
class ActivityService:
    def __init__(self, repo): self.repo=repo
    def record(self, action, object_id=None, **metadata):
        item=Activity(datetime.now(),action,object_id,metadata)
        if hasattr(self.repo,'record'): self.repo.record(item.timestamp,action,object_id,metadata)
        return item
    def today(self): return self.repo.today() if hasattr(self.repo,'today') else []
    def for_task(self,task): return []
