import asyncio
from uuid import uuid4
class NotConnected(RuntimeError): pass
class DeliveryUnknown(RuntimeError): pass
class OneBotClient:
    def __init__(self,timeout=20):
        self.timeout=timeout
        self.websocket=None
        self.pending={}
        self.lock=asyncio.Lock()
        self.late_receipt_handler=None
        self.late_tasks=set()
    @property
    def connected(self): return self.websocket is not None
    async def attach(self,ws):
        if self.websocket is not None: raise RuntimeError("already connected")
        self.websocket=ws
    async def detach(self,ws=None):
        if ws is not None and ws is not self.websocket: return
        self.websocket=None
        for f in self.pending.values():
            if not f.done(): f.set_exception(DeliveryUnknown("disconnected"))
    async def handle_receipt(self,response):
        echo=response.get("echo")
        if not isinstance(echo,str): return False
        future=self.pending.get(echo)
        if future is not None and not future.done(): future.set_result(response)
        elif self.late_receipt_handler:
            task=asyncio.create_task(self.late_receipt_handler(response))
            self.late_tasks.add(task)
            def done(t):
                self.late_tasks.discard(t)
                if not t.cancelled(): t.exception()
            task.add_done_callback(done)
        return True
    async def call(self,action,params,*,echo=None):
        if self.websocket is None: raise NotConnected()
        echo=echo or str(uuid4())
        if echo in self.pending: raise ValueError("duplicate echo")
        f=asyncio.get_running_loop().create_future()
        self.pending[echo]=f
        try:
            async with self.lock:
                if self.websocket is None: raise NotConnected()
                try:
                    await asyncio.wait_for(self.websocket.send_json({"action":action,"params":params,"echo":echo}),self.timeout)
                except Exception: raise DeliveryUnknown("dispatch uncertain") from None
            try: return await asyncio.wait_for(f,self.timeout)
            except Exception: raise DeliveryUnknown("receipt uncertain") from None
        finally:
            self.pending.pop(echo,None)
            if not f.done(): f.cancel()
    async def close(self):
        ws=self.websocket
        await self.detach()
        if ws:
            try: await ws.close()
            except Exception: pass
        for t in self.late_tasks: t.cancel()
        await asyncio.gather(*self.late_tasks,return_exceptions=True)
