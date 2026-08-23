class WordPressService:
    def __init__(self,adapter,outbox,activity): self.adapter=adapter; self.outbox=outbox; self.activity=activity
    def log(self,text,**metadata):
        payload={"kind":"log","text":text,"metadata":metadata}; self.outbox.enqueue(payload)
        try: return self.adapter.create_log(text,**metadata)
        except Exception: return payload
    def create_post(self,*a,**k): return self.adapter.create_post(*a,**k)
    def update_post(self,*a,**k): return self.adapter.update_post(*a,**k)
    def pending(self): return self.outbox.pending()
