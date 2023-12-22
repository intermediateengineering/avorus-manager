import json
from collections import deque
from typing import Any

from aiomqtt import Client as BaseClient
from paho.mqtt.client import Properties, ReasonCodes, Client as PahoClient


class Client(BaseClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._is_connected = False
        self._message_queue = deque()

    async def __aenter__(self):
        """Connect to the broker."""
        await self.connect()
        return self

    async def publish_json(self, topic: str, payload: object | None, **kwargs):
        if payload is not None:
            json_payload = json.dumps(payload)
        else:
            json_payload = None
        if self._is_connected:
            await self.publish(topic, json_payload, **kwargs)
        else:
            self._message_queue.append((topic, json_payload, kwargs))

    def _on_connect(self, client: PahoClient, userdata: Any, flags: dict[str, int], rc: int | ReasonCodes, properties: Properties | None = None) -> None:
        self._is_connected = True
        for _ in range(len(self._message_queue)):
            topic, json_payload, kwargs = self._message_queue.popleft()
            client.publish(topic, json_payload, **kwargs)
        return super()._on_connect(client, userdata, flags, rc, properties)

    def _on_disconnect(self, client: PahoClient, userdata: Any, rc: int | ReasonCodes | None, properties: Properties | None = None) -> None:
        self._is_connected = False
        return super()._on_disconnect(client, userdata, rc, properties)
