class HeadlessUI:
    def show(self,value): return value
    def __getattr__(self,name):
        def unavailable(*a,**k): raise RuntimeError(f'UI operation {name} unavailable in background service')
        return unavailable
