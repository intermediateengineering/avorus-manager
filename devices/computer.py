import asyncio
import json
import time

from misc import logger, memoize

from .device import DeviceState
from .wolable import WOLable

initial_state = {
    'temperatures': {},
    'fans': {},
    'boot_time': None,
    'uptime': None,
    'display': None,
    'errors': {},
    'is_muted': 1
}


class Computer(WOLable):
    _capabilities = ['wake', 'shutdown', 'reboot']

    def __init__(self,
                 *args,
                 ping_interval: float = 5,
                 ping_max_interval: float = 30,
                 shutdown_interval: float = 30,
                 reboot_interval: float = 30,
                 max_time_to_wake: float = 900,
                 max_time_to_shutdown: float = 900,
                 max_time_to_reboot: float = 900,
                 **kwargs):
        super().__init__(*args, should_icmp=False, **kwargs)
        self.timeouts['wake'] = max_time_to_wake
        self.timeouts['shutdown'] = max_time_to_shutdown
        self.timeouts['reboot'] = max_time_to_reboot
        self.intervals['ping'] = ping_interval
        self.intervals['ping_max_interval'] = ping_max_interval
        self.intervals['shutdown'] = shutdown_interval
        self.intervals['reboot'] = reboot_interval
        self.probe_address = f'manager/{self.name}'
        self._state['should_shutdown'] = False
        self._state['should_reboot'] = False
        for key, val in initial_state.items():
            self._state[key] = val
        self.last_ping_time = 0
        self.update_methods.append(('MQTT Watch online', self._watch_online))
        self.power_task = None
        self.probe_topic = f'probe/{self.name}/+'

        ip = getattr(self, 'primary_ip')
        address = ip['address'].split('/')[0]
        self.ip = address

    def __getattr__(self, __name):
        if __name.startswith('on_'):
            name = '_'.join(__name.split('_')[1:])

            async def method(args):
                method.__name__ = __name
                payload = json.loads(args)
                try:
                    result = payload['data']['result']
                    if self._state[name] != result:
                        self._state[name] = result
                        await self.event(name, self._state[name])
                except Exception as e:
                    if 'error' in payload:
                        raise Exception(payload['error']['message'],
                                        *payload['error']['errors'])
                    else:
                        await self._handle_exception(e)
            return method
        else:
            return getattr(self, __name)

    async def on_connect(self):
        await self.client.subscribe(self.probe_topic)

    async def on_temperatures(self, args):
        try:
            payload = json.loads(args)
            if 'data' in payload:
                self._state['temperatures'] = payload['data']['result']
                await self.event('temperatures', self._state['temperatures'])
            elif 'error' in payload:
                raise Exception(payload['error']['message'],
                                *payload['error']['errors'])
        except Exception as e:
            await self._handle_exception(e)

    async def on_fans(self, args):
        try:
            payload = json.loads(args)
            if 'data' in payload:
                self._state['fans'] = json.loads(args)['data']['result']
                await self.event('fans', self._state['fans'])
            elif 'error' in payload:
                raise Exception(payload['error']['message'],
                                *payload['error']['errors'])
        except Exception as e:
            await self._handle_exception(e)

    async def on_shutdown(self, _):
        pass

    async def online_event(self, _, event_type, value):
        if event_type == 'is_online':
            await self.set_should_wake(self.should_wake and value != DeviceState.ON)
            await self.set_should_shutdown(self.should_shutdown and value != DeviceState.OFF)
            await self.set_should_reboot(self.should_reboot and value != DeviceState.ON)
            if value != DeviceState.ON:
                for key, val in initial_state.items():
                    self._state[key] = val
                await self.event('boot_time', self._state['boot_time'])
                await self.event('uptime', self._state['uptime'])
                await self.event('temperatures', self._state['temperatures'])
                await self.event('fans', self._state['fans'])
                await self.event('errors', self._state['errors'])

    @property
    def should_shutdown(self) -> bool:
        return self._state['should_shutdown']

    async def set_should_shutdown(self, value: bool):
        self._state['should_shutdown'] = value
        await self.event('should_shutdown', value)

    @property
    def should_reboot(self) -> bool:
        return self._state['should_reboot']

    async def set_should_reboot(self, value: bool):
        self._state['should_reboot'] = value
        await self.event('should_reboot', value)

    @memoize('ping_interval')
    async def _watch_online(self):
        is_online = time.time() - self.last_ping_time < self.intervals['ping_max_interval']
        if is_online:
            if not self.should_reboot:
                await self.set_is_online(DeviceState.ON)
        else:
            await self.set_is_online(DeviceState.OFF)
            await self.client.unsubscribe(self.probe_topic)

    async def _shutdown(self):
        async with asyncio.timeout(self.timeouts['shutdown']):
            while self.should_shutdown:
                if self.is_online == DeviceState.ON:
                    self.last_ping_time = 0
                    await self.client.publish(f'{self.probe_address}/shutdown', qos=1)
                    await asyncio.sleep(self.intervals['shutdown'])
                elif self.is_online == DeviceState.OFF:
                    await self.set_should_shutdown(False)
                    await self.client.unsubscribe(self.probe_topic)

    async def _reboot(self):
        async with asyncio.timeout(self.timeouts['reboot']):
            while self.should_reboot:
                if self.is_online == DeviceState.ON:
                    await self.client.publish(f'{self.probe_address}/reboot', qos=1)
                    await asyncio.sleep(self.intervals['reboot_interval'])

    async def on_connected(self, *_):
        await self.set_is_online(DeviceState.ON)
        self.last_ping_time = time.time()

    async def on_ping(self, *_):
        if not self.should_reboot:
            await self.set_is_online(DeviceState.ON)
        self.last_ping_time = time.time()

    async def on_is_muted(self, args):
        try:
            payload = json.loads(args)
            if 'data' in payload:
                self._state['is_muted'] = payload['data']['result']
                await self.event('is_muted', self._state['is_muted'])
            elif 'error' in payload:
                raise Exception(payload['error']['message'],
                                *payload['error']['errors'])
        except Exception as e:
            await self._handle_exception(e)

    async def on_unmute(self, _):
        self._state['is_muted'] = False
        await self.event('is_muted', self._state['is_muted'])

    async def on_mute(self, _):
        self._state['is_muted'] = True
        await self.event('is_muted', self._state['is_muted'])

    async def on_mpv_file_pos_sec(self, _):
        pass

    async def shutdown(self, *_, **__):
        await self.cancel()
        logger.debug('Shutting down %s', self.name)
        await self.set_should_shutdown(self.is_online == DeviceState.ON)
        if 'shutdown' in self.tasks:
            self.tasks['shutdown'].cancel()
        task = asyncio.create_task(self._try_method(
            self._shutdown, error_cb=self.set_should_shutdown(False)))
        self.tasks['shutdown'] = task

        def power_off_done(_):
            logger.debug('%s power_off_done', self.name)
            self.power_cycle(wait=10)
            self._delete_task('shutdown')
        task.add_done_callback(power_off_done)

    async def reboot(self, *_, **__):
        await self.cancel()
        logger.debug('Reboot %s', self.name)
        await self.set_should_reboot(self.is_online == DeviceState.ON)
        if 'reboot' in self.tasks:
            self.tasks['reboot'].cancel()
        task = asyncio.create_task(self._try_method(
            self._reboot, error_cb=self.set_should_reboot(False)))
        self.tasks['reboot'] = task
        task.add_done_callback(self._delete_task('reboot'))

    async def mute(self, *_, **__):
        logger.debug('Mute %s', self.name)
        await self.client.publish(f'{self.probe_address}/mute', qos=1)

    async def unmute(self, *_, **__):
        logger.debug('Unmute %s', self.name)
        await self.client.publish(f'{self.probe_address}/unmute', qos=1)

    async def fetch(self):
        await super().fetch()
        await self.event('should_shutdown', self.should_shutdown)
        await self.event('should_reboot', self.should_reboot)
        await self.event('is_muted', self._state['is_muted'])
        await self.event('errors', self._state['errors'])
        await self.event('display', self._state['display'])
