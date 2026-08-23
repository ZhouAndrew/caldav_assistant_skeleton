class _IPC:
    def __init__(self,endpoint): self.endpoint=endpoint
class UnixSocketIPCClient(_IPC): pass
class UnixSocketIPCServer(_IPC): pass
class WindowsNamedPipeIPCClient(_IPC): pass
class WindowsNamedPipeIPCServer(_IPC): pass
