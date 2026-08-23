_registry=None
def bind_command_registry(registry):
    global _registry; _registry=registry
def command(name, **options):
    def deco(fn):
        if _registry is not None: _registry.register(name,fn,**options)
        setattr(fn,'__caldav_command__',name)
        return fn
    return deco
