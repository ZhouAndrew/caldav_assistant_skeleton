class PromptKit:
    def __init__(self,io,menu,temporal,tasks,events): self.io=io; self.menu=menu; self.temporal=temporal; self.tasks=tasks; self.events=events
    def show(self,value): return self.io.write(value) if hasattr(self.io,'write') else value
    def ask_text(self,prompt=''): return self.io.read(prompt)
    def ask_date(self,prompt='Date?'): return self.temporal.parse_date(self.io.read(prompt),bias='future')
    def ask_time(self,prompt='Time?'): return self.temporal.parse_time(self.io.read(prompt))
    def ask_datetime(self,prompt='Date/time?'): return self.temporal.parse_datetime(self.io.read(prompt),bias='future')
    def choose(self,title,items,**options): return self.menu.choose(title,items,**options)
    def confirm(self,text,**options): return self.io.read(text).strip().lower() in {'y','yes','1','true'}
    def choose_task(self,**filters): return self.menu.choose('Choose task',self.tasks.list(**filters))
    def choose_event(self,**filters): return self.menu.choose('Choose event',self.events.list(**filters))
