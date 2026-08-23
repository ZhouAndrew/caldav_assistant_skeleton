class HookRegistry:
    def __init__(self): self._hooks={}
    def register(self,event,fn): self._hooks.setdefault(event,[]).append(fn); return fn
    def emit(self,event,*a,**k): return [fn(*a,**k) for fn in self._hooks.get(event,[])]
