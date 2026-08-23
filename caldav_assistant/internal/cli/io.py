class StdConsoleIO:
    def read(self,prompt=''): return input(prompt + (' ' if prompt else ''))
    def write(self,value): print(value); return value
