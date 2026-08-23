class UndoManager:
    def __init__(self, repo): self.repo=repo
    def remember(self, payload):
        if hasattr(self.repo,'remember'): self.repo.remember(payload)
