class NotificationService:
    def __init__(self,adapter): self.adapter=adapter
    def send(self,title,body="",actions=None): return self.adapter.notify(title,body,actions)
