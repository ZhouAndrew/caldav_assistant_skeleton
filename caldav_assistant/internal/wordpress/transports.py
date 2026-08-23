class WPCLIAdapter:
    def create_log(self,text,**metadata): return {"text":text,**metadata}
    def create_post(self,*a,**k): return {"args":a,**k}
    def update_post(self,*a,**k): return {"args":a,**k}
    def test_connection(self): return True
