class ExtensionManager:
    def __init__(self,commands,hooks,settings): self.commands=commands; self.hooks=hooks; self.settings=settings
    def discover(self): return []
    def load(self,*a,**k): return None
