class CommandRegistry:
    def __init__(self): self._commands={}; self._protected=set()
    def register(self,name,handler,protected=False,override=False):
        if name in self._commands and not override: raise ValueError(f"Command {name} already exists")
        if name in self._protected and override: raise ValueError(f"Command {name} is protected")
        self._commands[name]=handler
        if protected:self._protected.add(name)
        return handler
    def get(self,name): return self._commands[name]
