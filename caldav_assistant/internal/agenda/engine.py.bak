from ...api import Agenda, AgendaItem
class AgendaEngine:
    def build(self,tasks,events,**kwargs):
        values=list(tasks)+list(events)
        return Agenda([AgendaItem(v,getattr(v,'due',None) or getattr(v,'start',None),'task' if hasattr(v,'due') else 'event') for v in values])
