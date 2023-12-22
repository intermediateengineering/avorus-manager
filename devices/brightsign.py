import requests
from requests.auth import HTTPDigestAuth

from .icmpable import ICMPable


class BrightSign(ICMPable):
    _capabilities = ['reboot']

    async def reboot(self, *_, **__):
        ip = self.primary_ip['address'].split('/')[0]
        requests.put(
            f'http://{ip}/api/v1/control/reboot',
            auth=HTTPDigestAuth('admin', 'avm'))
