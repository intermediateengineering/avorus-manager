from .device import DeviceState
from .wolable import WOLable
from misc import logger, memoize, run_in_thread
from functools import partial
import asyncio
import json

from pywebostv import connection, controls
import wsaccel
wsaccel.patch_ws4py()


store = {}


class LGWebOSTV(WOLable):
    _capabilities = ['wake', 'shutdown']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, should_icmp=False, **kwargs)
        self._state['should_shutdown'] = False
        self._state['is_webos_connected'] = False
        self.update_methods.append(('try_connect', self.try_connect))
        self.loop = asyncio.get_event_loop()

    async def online_event(self, _, event_type, value):
        if event_type == 'is_online':
            await self.set_should_wake(self.should_wake and not value)
            await self.set_should_shutdown(self.should_shutdown and value)

    @memoize(10)
    @run_in_thread
    def try_connect(self):
        if not self.is_webos_connected:
            self.webosclient = connection.WebOSClient(
                getattr(self, 'primary_ip')['address'].split('/')[0], secure=True)
            self.webosclient.closed = self.on_close
            self.syscontrol = controls.SystemControl(self.webosclient)
            try:
                self.webosclient.connect()
                with open('/opt/weboscreds.json', 'r+') as f:
                    store = json.loads(f.read())
                    list(self.webosclient.register(store, timeout=1))
                    f.seek(0)
                    f.write(json.dumps(store))
                    f.truncate()
                self.loop.create_task(self.set_is_online(DeviceState.ON))
                self.is_webos_connected = True
            except:
                pass

    @property
    def is_webos_connected(self):
        return self._state['is_webos_connected']

    @is_webos_connected.setter
    def is_webos_connected(self, value):
        self._state['is_webos_connected'] = DeviceState.ON if value else DeviceState.OFF
        self.loop.create_task(self.set_is_online(
            self._state['is_webos_connected']))

    @property
    def should_shutdown(self) -> bool:
        return self._state['should_shutdown']

    async def set_should_shutdown(self, value: bool):
        self._state['should_shutdown'] = value
        await self.event('should_shutdown', value)

    def on_close(self, *_, **kwargs):
        self.is_webos_connected = False

    def on_shutdown_received(self, status, payload):
        logger.debug('%s, %s', status, payload)
        self.loop.create_task(
            self.set_should_shutdown(status))

    async def shutdown(self, *_, **__):
        self.syscontrol.power_off(callback=self.on_shutdown_received)

    async def fetch(self):
        await self.event('is_online', self.is_online)
        await self.event('should_wake', self.should_wake)
        await self.event('capabilities', self.capabilities)
