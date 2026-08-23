class BuiltinActions:
    def __init__(self,ctx): self.ctx=ctx
    def today(self): return self.ctx.agenda.today()
    def next(self): return self.ctx.agenda.next()
    def done(self,task): return self.ctx.tasks.complete(task)
    def edit_due(self,task,due): return self.ctx.tasks.update(task,due=due)
