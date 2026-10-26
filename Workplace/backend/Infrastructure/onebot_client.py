from __future__ import annotations

import asyncio
from uuid import uuid4


class NotConnected(RuntimeError):
    """No request bytes were sent; a retry may be authorized by the worker."""


class DeliveryUnknown(RuntimeError):
    """The request may have reached QQ; never retry automatically."""


class OneBotClient:
    def __init__(self, timeout=20.0):
        self.timeout = timeout
        self.websocket = None
        self._pending = {}
        self._send_lock = asyncio.Lock()
        self.late_receipt_handler = None

    @property
    def connected(self):
        return self.websocket is not None

    async def attach(self, websocket):
        if self.websocket is not None and self.websocket is not websocket:
            raise RuntimeError("onebot connection already active")
        self.websocket = websocket

    async def detach(self, websocket=None):
        if websocket is not None and self.websocket is not websocket:
            return
        self.websocket = None
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(DeliveryUnknown("connection lost after dispatch"))

    async def handle_receipt(self, response):
        echo = response.get("echo")
        if not isinstance(echo, str):
            return False
        future = self._pending.get(echo)
        if future is not None and not future.done():
            future.set_result(response)
            return True
        if self.late_receipt_handler is not None:
            await self.late_receipt_handler(response)
        return True

    async def call(self, action, params, *, echo=None):
        if self.websocket is None:
            raise NotConnected("onebot is disconnected")
        echo = echo or str(uuid4())
        if echo in self._pending:
            raise ValueError("duplicate in-flight echo")
        future = asyncio.get_running_loop().create_future()
        self._pending[echo] = future
        sent = False
        try:
            async with self._send_lock:
                if self.websocket is None:
                    raise NotConnected("onebot disconnected before dispatch")
                sent = True
                await self.websocket.send_json({"action": action, "params": params, "echo": echo})
            return await asyncio.wait_for(future, timeout=self.timeout)
        except NotConnected:
            raise
        except (asyncio.TimeoutError, OSError, RuntimeError) as exc:
            raise DeliveryUnknown("onebot request outcome is unknown") from None
        finally:
            self._pending.pop(echo, None)
            if not future.done():
                future.cancel()
