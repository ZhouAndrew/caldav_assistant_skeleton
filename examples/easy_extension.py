"""Frozen acceptance example: a one-file simple extension."""
from caldav_assistant.easy import *

@command('urgent')
def urgent():
    show(overdue_tasks())
