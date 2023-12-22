class CalendarMixin:
    _capabilities = []

    def __init__(self,
                 *_,
                 **__):
        self.has_calendar_event = False
        self.last_calendar_method: str | None = None

    async def calendar_edge(self, edge, method_name):
        if edge == 'start':
            self.has_calendar_event = True
        else:
            self.has_calendar_event = False
        if method_name == 'clear':
            self.last_calendar_method = None
        else:
            self.last_calendar_method = method_name
