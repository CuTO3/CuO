"""FastAPI service: authenticated reverse WS, continuous intake, one business worker."""
import asyncio,hmac,logging
from contextlib import asynccontextmanager
from fastapi import FastAPI,WebSocket,WebSocketDisconnect,HTTPException,Request
from fastapi.responses import JSONResponse
from psycopg import sql
from config.settings import Settings
from database import Database
from database.cache import CacheManager
from Infrastructure.context import RuntimeContext
from Infrastructure.clock import now
from Infrastructure.model_client import ModelClient
from Infrastructure.onebot_client import OneBotClient
from Infrastructure.task_queue import TaskQueue
from Infrastructure.delivery import deliver,reconcile
from Infrastructure.results import result,save
from Infrastructure import archive
from receiver import receive_event
ERRORS={"multiple_intents":"要求太多啦，一次说一件事。","empty_input":"叫我做什么？说句话吧。",
"invalid_date":"是今天还是明天啊，我怎么看不明白吖","unsupported_date":"是今天还是明天啊，我怎么看不明白吖",
"future_date":"嗯...还没到那一天嘛，我不是占卜师喵","unsupported_intent":"还没做完QAQ","intention_failed":"听不懂喵","invalid_request":"你说的是啥喵"}
async def dispatch(task,ctx):
    from Function.intention import intention
    from Function.conversation import conversation
    from Function.memento import memento
    from Function.summary import summary
    from Function.divine import divine
    from Function.summary.son_function import image_processor
    from Infrastructure.admin import execute
    if task["business_status"]=="completed":return await deliver(task,ctx,task["result"])
    kind=task["request_type"]
    if kind=="message":
        p=task["params"]
        if "_opt" not in p:
            intent=await intention.run(p.get("request_text",task.get("original_text") or ""),task["triggered_at"],context=ctx,group_id=task["group_id"])
            p.update(intent["params"]);p["_opt"]=intent["opt"]
            await ctx.db.write("log",[{"task_id":task["task_id"],"params":p,"step":"classified"}],group_id=task["group_id"],mode="update",key_fields=("task_id",))
        kind=p["_opt"]
        if kind=="error":
            value=await save(task,ctx,result("error",error_code=p.get("code"),actions=[{"type":"send_message","text":ERRORS.get(p.get("code"),ERRORS["invalid_request"])}]))
            return await deliver(task,ctx,value)
    handlers={"conversation":conversation.run,"memento":memento.run,"summary":summary.run,"divine":divine.run,
              "media_describe":image_processor.run,"archive_day":archive.run,"initialize_day":archive.run,"admin_update":execute}
    if kind not in handlers:raise ValueError("unsupported task type")
    value=await handlers[kind](task,ctx)
    rows=await ctx.db.read("log",group_id=task["group_id"],filters={"task_id":task["task_id"]},limit=1)
    if rows[0]["business_status"]!="completed":
        if value.get("status")=="error":
            await ctx.db.write("log",[{"task_id":task["task_id"],"status":"needs_review","step":value.get("error_code") or "business_review","error":{"code":value.get("error_code")}}],group_id=task["group_id"],mode="update",key_fields=("task_id",))
            return
        await save(task,ctx,value)
    await deliver(task,ctx,value)

async def verify_schema(db):
    for gid in db.groups:
        rows=await db.fetch(gid,"SELECT current_database() AS name, obj_description(oid,'pg_namespace') AS version FROM pg_namespace WHERE nspname=%s",(db.schemas[gid],))
        if not rows or rows[0]["name"]!="CuO" or rows[0]["version"]!="cuo-schema-v1":raise RuntimeError("run reviewed migration before startup")
        for table in ("log","messages","members","summaries","divinations"):
            await db.fetch(gid,sql.SQL("SELECT 1 FROM {} LIMIT 0").format(db.table(gid,table)))

def create_app(settings=None):
    @asynccontextmanager
    async def lifespan(app):
        s=settings or Settings.load()
        if not s.napcat_token or not s.self_id:raise RuntimeError("ONEBOT_TOKEN and ONEBOT_SELF_ID required")
        db=Database(s);model=ModelClient(s);onebot=OneBotClient(s.onebot_timeout)
        ctx=RuntimeContext(s,db,model,onebot);app.state.ctx=ctx
        ctx.cache=CacheManager(s,db);ctx.queue=TaskQueue(ctx,dispatch)
        app.state.inbound=asyncio.Queue(maxsize=s.inbound_queue_size)
        consumer=None;scheduler=None
        try:
            await db.open();await verify_schema(db)
            from Function.divine.son_function.zhou_yi import load_hexagrams
            load_hexagrams()
            await ctx.queue.start(launch=False)
            from Function.intention.intention import synchronize
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
            await ctx.queue.stop();await onebot.close();await model.close();await db.close()
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
    from Infrastructure.admin import install
    install(app)
    return app
app=create_app()
