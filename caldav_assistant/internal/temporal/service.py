class TemporalService:
    def __init__(self, parser): self.parser=parser
    def parse_date(self,*a,**k): return self.parser.parse_date(*a,**k)
    def parse_time(self,*a,**k): return self.parser.parse_time(*a,**k)
    def parse_datetime(self,*a,**k): return self.parser.parse_datetime(*a,**k)
