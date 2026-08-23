class Menu:
    def __init__(self,io): self.io=io
    def choose(self,title,items,multiple=False,**options):
        values=list(items)
        return values if multiple else (values[0] if values else None)
