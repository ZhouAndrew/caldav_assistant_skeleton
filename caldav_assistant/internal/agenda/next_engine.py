class NextEngine:
    def choose(self, tasks, events, current=None, kind=None, **kwargs):
        if current is not None and kind in (None,'task'): return current
        candidates=list(tasks) if kind=='task' else list(events) if kind=='event' else list(tasks)+list(events)
        return candidates[0] if candidates else None
