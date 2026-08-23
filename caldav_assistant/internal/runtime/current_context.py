_current=None
def bind_current_context(ctx):
    global _current; _current=ctx; return ctx
def get_current_context():
    if _current is None: raise RuntimeError("No AssistantContext is bound")
    return _current
