from typing import Callable

from misc import BroadcastEvent


class EventMixin:
    def __init__(self,
                 manager, client,
                 callback: Callable,
                 **kwargs):
        id: int = kwargs['id']
        self.event = BroadcastEvent(id)
        self.event.append(callback)
