class _Base:
    def notify(self,title,body="",actions=None): return {"title":title,"body":body,"actions":actions}
class LinuxNotificationAdapter(_Base): pass
class MacOSNotificationAdapter(_Base): pass
class WindowsNotificationAdapter(_Base): pass
