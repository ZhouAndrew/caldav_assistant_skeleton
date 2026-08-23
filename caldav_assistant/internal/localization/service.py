class LocaleService:
    def __init__(self,locale='en'): self.locale=locale
    def get(self,key,default=None,**kwargs): return (default or key).format(**kwargs)
