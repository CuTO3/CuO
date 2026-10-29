'''
本文件用途：FastAPI service: authenticated reverse WS, continuous intake, one business worker.

配置字段：
inbound_queue_size                   接收队列容量
napcat_token                         NapCat 接入凭据
onebot_timeout                       OneBot 调用超时（秒）
self_id                              机器人账号标识
'''

import asyncio,hmac,logging
from contextlib import asynccontextmanager
from fastapi import FastAPI,WebSocket,WebSocketDisconnect,HTTPException,Request
from fastapi.responses import JSONResponse
from psycopg import sql
from Core.settings import Settings
from Integration.postgresql import Database
from Core.cache import CacheManager
from Core.context import RuntimeContext
from Core.clock import now
from Integration.litellm.client import ModelClient
from Integration.napcat.client import OneBotClient
from Core.task_queue import TaskQueue
from Integration.napcat.delivery import deliver,reconcile
from Core.results import result,save
from Core import archive
from Workflow._receiver_ import receive_event
async def dispatch(task,ctx):
    from Workflow import _analyzer_, _router_
    if task["business_status"]=="completed":return await deliver(task,ctx,task["result"])
    kind=await _analyzer_.classify_task(task,ctx)
    value=await _router_.route(task,ctx,kind)
    if value is not None:await deliver(task,ctx,value)

async def verify_schema(db):
    for gid in db.groups:
        rows=await db.fetch(gid,"SELECT current_database() AS name, obj_description(oid,'pg_namespace') AS version FROM pg_namespace WHERE nspname=%s",(db.schemas[gid],))
        if not rows or rows[0]["name"]!="CuO" or rows[0]["version"]!="cuo-schema-v2":raise RuntimeError("run reviewed migration before startup")
        for table in ("log","messages","members","summaries","divinations"):
            await db.fetch(gid,sql.SQL("SELECT 1 FROM {} LIMIT 0").format(db.table(gid,table)))

def create_app(settings=None):
    @asynccontextmanager
    async def lifespan(app):
        s=settings or Settings.load()
        if not s.napcat_token or not s.self_id:raise RuntimeError("ONEBOT_TOKEN and ONEBOT_SELF_ID required")
        db=Database(s);model=None;onebot=OneBotClient(s.onebot_timeout)
        ctx=RuntimeContext(s,db,model,onebot);app.state.ctx=ctx
        ctx.cache=CacheManager(s,db);ctx.queue=TaskQueue(ctx,dispatch)
        app.state.inbound=asyncio.Queue(maxsize=s.inbound_queue_size)
        consumer=None;scheduler=None
        try:
            await db.open();await verify_schema(db)
            from Function.divine.son_function.zhou_yi import load_hexagrams
            load_hexagrams()
            from Function.divine.son_function.readings import load_readings
            load_readings()
            await ctx.queue.start(launch=False)
            from Workflow._analyzer_ import synchronize
            await synchronize(ctx)
            db.set_cache(ctx.cache);await ctx.cache.startup()
            onebot.late_receipt_handler=lambda response:reconcile(ctx,response)
            async def consume():
                while True:
                    event,instant=await app.state.inbound.get()
                    try:await receive_event(event,instant,context=ctx)
                    except asyncio.CancelledError:raise
                    except Exception:
                        ctx.ready=False
                        logging.getLogger(__name__).exception("inbound persistence failed")
                        if onebot.websocket:await onebot.websocket.close(code=1011)
                    finally:app.state.inbound.task_done()
            consumer=asyncio.create_task(consume());scheduler=asyncio.create_task(archive.scheduler(ctx))
            ctx.ready=True;ctx.queue.launch()
            yield
        finally:
            ctx.ready=False
            if onebot.websocket:await onebot.websocket.close(code=1001)
            if scheduler:scheduler.cancel();await asyncio.gather(scheduler,return_exceptions=True)
            if consumer:
                try:await asyncio.wait_for(app.state.inbound.join(),30)
                except TimeoutError:pass
                consumer.cancel();await asyncio.gather(consumer,return_exceptions=True)
            await ctx.queue.stop();await onebot.close();await db.close()
    app=FastAPI(lifespan=lifespan)
    @app.get("/health")
    async def health():return {"status":"alive"}
    @app.get("/ready")
    async def ready():
        ctx=getattr(app.state,"ctx",None)
        return JSONResponse({"ready":bool(ctx and ctx.ready),"onebot_connected":bool(ctx and ctx.onebot.connected)},status_code=200 if ctx and ctx.ready else 503)
    @app.websocket("/onebot/ws")
    async def websocket(ws:WebSocket):
        ctx=app.state.ctx
        token=ws.headers.get("authorization","")
        if not hmac.compare_digest(token,"Bearer "+ctx.settings.napcat_token) or ws.headers.get("x-self-id")!=ctx.settings.self_id:
            await ws.close(code=1008);return
        if not ctx.ready or ctx.onebot.connected:await ws.close(code=1013);return
        await ws.accept();await ctx.onebot.attach(ws)
        try:
            while True:
                event=await ws.receive_json()
                if not isinstance(event,dict):continue
                if "echo" in event and "post_type" not in event:
                    await ctx.onebot.handle_receipt(event);continue
                if str(event.get("self_id",""))!=ctx.settings.self_id:continue
                try:app.state.inbound.put_nowait((event,now()))
                except asyncio.QueueFull:
                    # Stop accepting rather than silently evict an older event.
                    await ws.close(code=1013);break
        except WebSocketDisconnect:pass
        finally:await ctx.onebot.detach(ws)
    from Integration.console.admin import install
    install(app)
    from Integration.console.routes import install as install_console
    install_console(app)
    return app
app=create_app()
