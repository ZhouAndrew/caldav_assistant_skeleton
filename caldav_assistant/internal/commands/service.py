class CommandService:
    def __init__(self,registry): self.registry=registry
    def register(self,*a,**k): return self.registry.register(*a,**k)
    def run(self,name,*a,**k): return self.registry.get(name)(*a,**k)
