from dataclasses import dataclass
@dataclass
class ActionRequest:
    action: str
    target: str|None=None
    parameters: dict|None=None
class IntentParser:
    def parse(self,text): return ActionRequest('unknown',parameters={'text':text})
