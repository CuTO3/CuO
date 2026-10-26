"""Revisioned daily snapshots, scheduled without sending or deleting source messages."""
import asyncio,hashlib,json,logging
from datetime import date,timedelta
from uuid import uuid5,NAMESPACE_URL
from Infrastructure.clock import now,business_date,day_bounds
from Infrastructure.results import result,save,saved,jsonable
def digest(rows):
    return hashlib.sha256(json.dumps(jsonable(rows),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
async def enqueue(ctx,gid,day,kind,revision,source_hash):
    tid=str(uuid5(NAMESPACE_URL,f"cuo:{gid}:{kind}:{day}:{revision}:{source_hash}"))
    existing=await ctx.db.read("log",group_id=gid,filters={"task_id":tid},limit=1)
    if existing:return
    instant=now()
    await ctx.db.write("log",[{"task_id":tid,"triggered_at":instant,"business_date":day,"request_type":kind,
        "params":{"revision":revision,"source_hash":source_hash}}],group_id=gid)
    ctx.queue.wake()
async def schedule(ctx):
    today=business_date(now())
    for gid in ctx.db.groups:
        first=await ctx.db.read("messages",group_id=gid,filters={},order_by=(("business_date","asc"),),limit=1)
        start=date.fromisoformat(ctx.settings.first_business_date) if ctx.settings.first_business_date else first[0]["business_date"] if first else today
        day=start
        while day<today:
            rows=await ctx.db.read("messages",group_id=gid,filters={"business_date":day},order_by=(("sent_at","asc"),("id","asc")))
            h=digest(rows)
            logs=await ctx.db.read("log",group_id=gid,filters={"request_type":"archive_day","business_date":day},order_by=(("created_at","desc"),))
            if not logs or not any(r["params"].get("source_hash")==h for r in logs):
                revision=max((r["params"].get("revision",0) for r in logs),default=0)+1
                for r in logs:
                    if r["business_status"]=="completed" and not r["result"].get("source_dirty"):
                        await ctx.db.write("log",[{"task_id":r["task_id"],"result":{**r["result"],"source_dirty":True}}],group_id=gid,mode="update",key_fields=("task_id",))
                await enqueue(ctx,gid,day,"archive_day",revision,h)
            day+=timedelta(days=1)
        yesterday=today-timedelta(days=1)
        rows=await ctx.db.read("messages",group_id=gid,filters={"business_date":yesterday},order_by=(("sent_at","asc"),("id","asc")))
        h=digest(rows)
        init=await ctx.db.read("log",group_id=gid,filters={"request_type":"initialize_day","business_date":today},order_by=(("created_at","desc"),))
        if not any(r["params"].get("source_hash")==h for r in init):
            for r in init:
                if r["business_status"]=="completed":await ctx.db.write("log",[{"task_id":r["task_id"],"result":{**r["result"],"source_dirty":True}}],group_id=gid,mode="update",key_fields=("task_id",))
            await enqueue(ctx,gid,today,"initialize_day",len(init)+1,h)
async def run(task,ctx):
    old=await saved(task,ctx)
    if old is not None:return old
    gid=task["group_id"];day=task["business_date"];kind=task["request_type"]
    source_day=day-timedelta(days=1) if kind=="initialize_day" else day
    if kind=="archive_day" and day>=business_date(now()):raise ValueError("cannot archive unfinished day")
    rows=await ctx.db.read("messages",group_id=gid,filters={"business_date":source_day},order_by=(("sent_at","asc"),("id","asc")))
    from Function.summary.son_function.normalize_messages import normalize_messages
    from Function.divine.divine import candidates_from
    records,mapping=await normalize_messages(rows,ctx,gid)
    candidates=candidates_from(records,mapping,"")
    keywords={"business_date":str(day),"source_business_date":str(source_day),"source_status":"ready" if records else "no_data","items":candidates}
    start,end=day_bounds(source_day)
    value=result(business_date=str(day),coverage_start=start.isoformat(),coverage_end=end.isoformat(),
        revision=task["params"]["revision"],source_hash=digest(rows),source_dirty=False,message_count=len(rows),
        raw_snapshot=jsonable(rows) if kind=="archive_day" else [],keywords=keywords,
        mentions=[{"ref":r["ref"],"mentions":r["mentions"]} for r in records if r["mentions"]])
    await save(task,ctx,value)
    if ctx.cache:
        await ctx.cache.refresh_day(gid,day)
        if kind=="initialize_day":
            await ctx.cache.set_current(gid,day,task["task_id"])
            await ctx.cache.prune(gid,day)
    return value
async def scheduler(ctx):
    while True:
        try:await schedule(ctx)
        except asyncio.CancelledError:raise
        except Exception:logging.getLogger(__name__).exception("archive scheduling failed")
        await asyncio.sleep(60)
