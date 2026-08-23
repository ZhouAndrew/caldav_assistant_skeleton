"""Scratch-style composition acceptance example."""
from caldav_assistant.easy import *

@command('finish')
def finish():
    task = choose_task()
    if confirm(f'Complete {task.summary}?'):
        show(complete(task))
