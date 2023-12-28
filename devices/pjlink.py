import asyncio
import os

from aiopjlink import Projector

from misc import logger, memoize

from .device import Device, DeviceState
from .icmpable import ping_address

WAKE_INTERVAL = 30
SHUTDOWN_INTERVAL = 30

initial_state = {
    'errors': {},
    'lamps': [],
    'ires': '',
    'warming': False,
    'cooling': False
}


class PJLink(Device):
    _capabilities = ['wake', 'shutdown']

    def __init__(self, *args, max_time_to_wake: float = 900, max_time_to_shutdown=900, **kwargs):
        super().__init__(*args, **kwargs)
        self._state['should_wake'] = False
        self._state['should_shutdown'] = False
        self._state['watch_failed'] = False
        self.reset_state()

        self.timeouts['wake'] = max_time_to_wake
        self.timeouts['shutdown'] = max_time_to_shutdown

        self.event.append(self.online_event)

        ip = getattr(self, 'primary_ip')
        address = ip['address'].split('/')[0]
        self.ip = address
        self.device = Projector(
            address, password=os.environ['PJLINK_PASSWORD'])

        self.update_methods.append(('PJLink watch', self._watch))

    def reset_state(self):
        for key, value in initial_state.items():
            self._state[key] = value

    async def set_power_state(self, power_state):
        match power_state:
            case 'on':
                await self.set_is_online(DeviceState.ON)
                self._state['warming'] = False
                self._state['cooling'] = False
            case 'warming':
                await self.set_is_online(DeviceState.PARTIAL)
                self._state['warming'] = True
                self._state['cooling'] = False
            case 'cooling':
                await self.set_is_online(DeviceState.PARTIAL)
                self._state['warming'] = False
                self._state['cooling'] = True
            case 'off':
                await self.set_is_online(DeviceState.PARTIAL)
                self._state['warming'] = False
                self._state['cooling'] = False

    @memoize(10, immediate_key='watch_failed')
    async def _watch(self):
        if await ping_address(self.ip):
            try:
                async with asyncio.timeout(max(self.timeouts.values())):
                    await self.lock.acquire()
            except:
                await self.cancel()
                self.device = Projector(
                    self.ip, password=os.environ['PJLINK_PASSWORD'])
                return
            try:
                async with self.device as device:
                    await device.authenticate()
                    power_state = await device.get_power()
                    await self.set_power_state(power_state)
                    await self._watch_status(device)
                    self._state['watch_failed'] = False
            except Exception as e:
                self._state['watch_failed'] = True
                await self._handle_exception(e)
                self.device = Projector(
                    self.ip, password=os.environ['PJLINK_PASSWORD'])
            self.lock.release()
        else:
            await self.set_is_online(DeviceState.OFF)

    async def _watch_status(self, device):
        if 'class' not in self._state:
            self._state['class'] = await device.get_class()
        try:
            errors = await device.get_errors()
        except:
            errors = self._state['errors']
        try:
            lamps = await device.get_lamps()
        except:
            lamps = []

        has_lamps_event = self._state['lamps'] != len(lamps)
        if has_lamps_event:
            self._state['lamps'] = lamps
        else:
            for i, lamp in enumerate(lamps):
                for j, value in enumerate(lamp):
                    if self._state['lamps'][i][j] != value:
                        self._state['lamps'][i][j] = value
                        has_lamps_event = True
        if has_lamps_event:
            await self.event('lamps', self._state['lamps'])

        has_error_event = False
        for key, value in errors.items():
            if key not in self._state['errors'] or self._state['errors'][key] != value:
                has_error_event = True
                self._state['errors'][key] = value
        if has_error_event:
            await self.event('errors', self._state['errors'])

        if self._state['class'] == 2:
            try:
                ires = await device.get_ires()
                if ires != self._state['ires']:
                    self._state['ires'] = ires
                    await self.event('ires', self._state['ires'])
            except:
                pass

    async def _wake(self):
        async with asyncio.timeout(self.timeouts['wake']):
            while self.should_wake:
                if self.is_online in [DeviceState.OFF, DeviceState.PARTIAL]:
                    await self.lock.acquire()
                    try:
                        async with self.device as device:
                            await device.authenticate()
                            logger.debug(
                                'Authentication succeeded, set_power on')
                            await device.set_power('on')
                    except Exception as e:
                        await self._handle_exception(e)
                    self.lock.release()
                    await asyncio.sleep(WAKE_INTERVAL)
                elif self.is_online == DeviceState.ON:
                    await self.set_should_wake(False)

    async def _shutdown(self):
        async with asyncio.timeout(self.timeouts['shutdown']):
            while self.should_shutdown:
                if self.is_online == DeviceState.ON:
                    logger.debug('Try shutdown %s', self.name)
                    await self.lock.acquire()
                    try:
                        async with self.device as device:
                            await device.authenticate()
                            logger.debug(
                                'Authentication succeeded, set_power off')
                            await device.set_power('off')
                            self.power_off(300)
                    except Exception as e:
                        await self._handle_exception(e)
                    self.lock.release()
                    await asyncio.sleep(SHUTDOWN_INTERVAL)
                elif self.is_online in [DeviceState.OFF, DeviceState.PARTIAL]:
                    await self.set_should_shutdown(False)

    async def online_event(self, _, event_type, value):
        if event_type == 'is_online':
            await self.set_should_wake(self.should_wake and value != DeviceState.ON)
            await self.set_should_shutdown(self.should_shutdown and value not in [DeviceState.OFF, DeviceState.PARTIAL])
            if value != DeviceState.ON:
                self.reset_state()

    @property
    def should_wake(self) -> bool:
        return self._state['should_wake']

    @property
    def watch_failed(self) -> bool:
        return self._state['watch_failed']

    async def set_should_wake(self, value: bool):
        self._state['should_wake'] = value
        await self.event('should_wake', value)

    @property
    def should_shutdown(self) -> bool:
        return self._state['should_shutdown']

    async def set_should_shutdown(self, value: bool):
        self._state['should_shutdown'] = value
        await self.event('should_shutdown', value)

    async def wake(self, *_, **__):
        self._cancel_existing_power_task()
        await self.cancel()
        logger.debug('Waking %s', self.name)
        has_pdu = await self.set_power(True)

        async def inner():
            if has_pdu:
                logger.debug('PDU switched. Deferring wake. %s', self.name)
                await asyncio.sleep(10)
            await self.set_should_wake(self.is_online in [DeviceState.OFF, DeviceState.PARTIAL])
            await self._wake()

        if 'wake' in self.tasks:
            self.tasks['wake'].cancel()
        task = asyncio.create_task(self._try_method(
            inner, error_cb=self.set_should_wake(False)))
        self.tasks['wake'] = task
        task.add_done_callback(self._delete_task('wake'))

    async def shutdown(self, *_, **__):
        await self.cancel()
        logger.debug('Shutting down %s', self.name)
        await self.set_should_shutdown(True)
        if 'shutdown' in self.tasks:
            self.tasks['shutdown'].cancel()
        task = asyncio.create_task(self._try_method(
            self._shutdown, error_cb=self.set_should_shutdown(False)))
        self.tasks['shutdown'] = task

        def power_off_done(_):
            self.power_off()
            self._delete_task('shutdown')
        task.add_done_callback(power_off_done)

    async def fetch(self):
        await super().fetch()
        await self.event('should_wake', self.should_wake)
        await self.event('errors', self._state['errors'])
        await self.event('lamps', self._state['lamps'])
        await self.event('ires', self._state['ires'])
