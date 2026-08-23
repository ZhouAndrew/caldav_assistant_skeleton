from __future__ import annotations
class RuntimeDispatcher:
    def __init__(self,ctx):
        self.ctx=ctx
        self._routes={'tasks.list':ctx.tasks.list,'tasks.find':ctx.tasks.find,'tasks.get':ctx.tasks.get,'tasks.create':ctx.tasks.create,'tasks.update':ctx.tasks.update,'tasks.complete':ctx.tasks.complete,'tasks.start':ctx.tasks.start,'tasks.pause':ctx.tasks.pause,'tasks.resume':ctx.tasks.resume,'tasks.delete':ctx.tasks.delete,'events.list':ctx.events.list,'events.find':ctx.events.find,'events.get':ctx.events.get,'events.create':ctx.events.create,'events.update':ctx.events.update,'events.delete':ctx.events.delete,'agenda.today':ctx.agenda.today,'agenda.range':ctx.agenda.range,'agenda.next':ctx.agenda.next,'agenda.overdue':ctx.agenda.overdue,'reminders.list':ctx.reminders.list,'reminders.create':ctx.reminders.create,'reminders.snooze':ctx.reminders.snooze,'reminders.cancel':ctx.reminders.cancel,'notifications.send':ctx.notifications.send,'wordpress.log':ctx.wordpress.log,'wordpress.create_post':ctx.wordpress.create_post,'wordpress.update_post':ctx.wordpress.update_post,'wordpress.pending':ctx.wordpress.pending,'activity.today':ctx.activity.today,'activity.for_task':ctx.activity.for_task,'activity.record':ctx.activity.record,'settings.get':ctx.settings.get,'settings.set':ctx.settings.set}
    def handle(self,method,payload=None):
        if method not in self._routes: raise ValueError(f"IPC method is not allowed: {method}")
        return self._routes[method](**(payload or {}))
