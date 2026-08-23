class SettingsService:
    def __init__(self, repository): self._repository=repository
    def get(self, key, default=None): return self._repository.get(key, default)
    def set(self, key, value): self._repository.set(key, value); return value
    def delete(self, key): return self._repository.delete(key)
