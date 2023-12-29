import asyncio

from wakeonlan import send_magic_packet

from misc import logger

from .device import DeviceState
from .icmpable import ICMPable


class WOLable(ICMPable):
    _capabilities = ['wake']

    def __init__(self, *args, wake_interval: float = 60, max_time_to_wake: float = 900, **kwargs):
        super().__init__(*args, **kwargs)
        self._state['should_wake'] = False
        self.intervals['wake_interval'] = wake_interval
        self.timeouts['wake'] = max_time_to_wake
        self.event.append(self.online_event)

    async def online_event(self, _, event_type, value):
        if event_type == 'is_online':
            await self.set_should_wake(self.should_wake and value != DeviceState.ON)

    @property
    def should_wake(self) -> bool:
        return self._state['should_wake']

    async def set_should_wake(self, value: bool):
        self._state['should_wake'] = value
        await self.event('should_wake', value)

    async def _wake(self):
        async with asyncio.timeout(self.timeouts['wake']):
            while self.should_wake:
                if not self.is_online == DeviceState.ON:
                    interfaces = getattr(self, 'interfaces')
                    for interface in interfaces:
                        if self.is_online == DeviceState.ON:
                            await self.set_should_wake(False)
                            break
                        mac_address: str = interface['mac_address']
                        if mac_address:
                            send_magic_packet(mac_address)
                        else:
                            await self.set_should_wake(False)
                    await asyncio.sleep(self.intervals['wake_interval'])
                elif self.is_online == DeviceState.ON:
                    await self.set_should_wake(False)

    async def wake(self, *_, **__):
        try:
            await self.cancel()
        except:
            pass
        self._cancel_existing_power_task()
        has_pdu = await self.set_power(True)
        logger.debug('Waking %s', self.name)

        async def inner():
            if has_pdu:
                await asyncio.sleep(5)
            await self.set_should_wake(True)
            await self._wake()

        if 'wake' in self.tasks:
            self.tasks['wake'].cancel()
        task = asyncio.create_task(self._try_method(
            inner, error_cb=self.set_should_wake(False)))
        self.tasks['wake'] = task
        task.add_done_callback(self._delete_task('wake'))

    async def fetch(self):
        await super().fetch()
        await self.event('should_wake', self.should_wake)
