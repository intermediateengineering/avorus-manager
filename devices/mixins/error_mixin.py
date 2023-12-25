import sys
import traceback
import json
import time
import asyncio
from typing import Coroutine

from aiomqtt import Client

from misc import logger


class ErrorMixin:
    def __init__(self,
                 manager,
                 client: Client,
                 *_,
                 **kwargs):
        self.manager = manager
        self.client = client
        try:
            self.name = kwargs['primary_ip']['dns_name']
        except Exception:
            self.name = kwargs['name']

    async def _handle_exception(self, e):
        _, _, tb = sys.exc_info()
        tb_info = traceback.extract_tb(tb)
        _, _, func, text = tb_info[-1]
        error_name = f'[{self.name}]: {func}: {type(e).__name__} {text}'
        logger.debug('%s %s', error_name, e)
        await self.error(error_name, e.args)

    async def error(self, message: str, errors: tuple = ()):
        json_payload = json.dumps({
            'error': {
                'message': message,
                'errors': errors,
                'time': time.time() * 1000
            }
        })
        await self.client.publish('manager/device_event', json_payload)

    async def _try_method(self, method, error_cb: Coroutine | None = None, **kwargs):
        try:
            if self.timeouts.values():
                timeout = max(self.timeouts.values())
            else:
                timeout = 60
            async with asyncio.timeout(timeout):
                await method(**kwargs)
                if error_cb:
                    error_cb.close()
        except Exception as e:
            try:
                self.lock.release()
            except:
                pass
            if error_cb:
                await error_cb
            logger.exception(self.name)
            await self._handle_exception(e)
