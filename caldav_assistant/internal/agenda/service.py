class AgendaService:
    def __init__(self,tasks,events,engine,next_engine,state): self.tasks=tasks; self.events=events; self.engine=engine; self.next_engine=next_engine; self.state=state
    def today(self): return self.engine.build(self.tasks.list(today=True),self.events.list(today=True))
    def range(self,days=1,**filters): return self.engine.build(self.tasks.list(**filters),self.events.list(**filters),days=days)
    def next(self,kind=None,**options): return self.next_engine.choose(self.tasks.list(),self.events.list(),kind=kind,**options)
    def overdue(self): return self.tasks.list(overdue=True)
