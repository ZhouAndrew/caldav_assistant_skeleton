class SyncEngine:
    def __init__(self, adapter, cache): self.adapter=adapter; self.cache=cache
    def refresh(self): return None
    def incremental_sync(self): return None
