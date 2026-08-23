class RuntimeClient:
    def __init__(self,ipc,launcher=None): self.ipc=ipc; self.launcher=launcher
    def call(self,method,**payload):
        if hasattr(self.ipc,'call'): return self.ipc.call(method,payload)
        if hasattr(self.ipc,'request'): return self.ipc.request(method,payload)
        raise RuntimeError('IPC adapter has no call/request method')
