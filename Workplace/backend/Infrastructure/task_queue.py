"""One global worker, guarded by a dedicated PostgreSQL advisory-lock session."""
import asyncio,logging
from datetime import datetime,timedelta
from psycopg import AsyncConnection
from Infrastructure.clock import now
from Infrastructure.results import jsonable
from Infrastructure.delivery import RetryDelivery
LOG=logging.getLogger(__name__)
LOCK_ID=485879970503
class TaskQueue:
    def __init__(self,ctx,dispatch):
        self.ctx=ctx;self.dispatch=dispatch;self.event=asyncio.Event();self.stopping=False
        self.worker=None;self.lease=None
    def wake(self):self.event.set()
    async def start(self,launch=True):
        self.lease=await AsyncConnection.connect(self.ctx.settings.database_url,autocommit=True)
        row=await (await self.lease.execute("SELECT pg_try_advisory_lock(%s)",(LOCK_ID,))).fetchone()
        if not row[0]:
            await self.lease.close();self.lease=None
            raise RuntimeError("another CuO worker owns the database")
        await self.recover()
        if launch:self.launch()
    def launch(self):
        self.worker=asyncio.create_task(self.loop())
    async def recover(self):
        for gid in self.ctx.db.groups:
            rows=await self.ctx.db.read("log",group_id=gid,filters={"status":"running"})
            for row in rows:
                value=row["result"];ambiguous=False
                for action in value.get("actions",[]):
                    if action.get("status") in ("sending","unknown"):
                        action["status"]="unknown";ambiguous=True
                await self.ctx.db.write("log",[{"task_id":row["task_id"],"status":"needs_review" if ambiguous else "pending","result":value,"step":"recovered"}],group_id=gid,mode="update",key_fields=("task_id",))
    async def claim(self):
        await self.lease.execute("SELECT 1")  # Losing the lock connection stops consumption.
        candidates=[]
        instant=now()
        for gid in self.ctx.db.groups:
            rows=await self.ctx.db.read("log",group_id=gid,filters={"status":"pending"},order_by=(("created_at","asc"),))
            for row in rows:
                retry=row["params"].get("_retry_at")
                if retry and datetime.fromisoformat(retry)>instant:continue
                row["group_id"]=gid;candidates.append(row)
        if not candidates:return None
        task=min(candidates,key=lambda r:(r["created_at"],r["params"].get("queue",{}).get("batch_seq",0),r["params"].get("queue",{}).get("order",0),str(r["task_id"])))
        await self.ctx.db.write("log",[{"task_id":task["task_id"],"status":"running","step":"claimed"}],group_id=task["group_id"],mode="update",key_fields=("task_id",))
        return task
    async def fail(self,task,exc):
        rows=await self.ctx.db.read("log",group_id=task["group_id"],filters={"task_id":task["task_id"]},limit=1)
        row=rows[0];value=row["result"];p=row["params"]
        ambiguous=any(a.get("status") in ("sending","unknown") for a in value.get("actions",[]))
        for a in value.get("actions",[]):
            if a.get("status")=="sending":a["status"]="unknown"
        count=p.get("_retry_count",0)
        retry=not ambiguous and count<3 and not isinstance(exc,(ValueError,TypeError,KeyError))
        if retry:
            p["_retry_count"]=count+1;p["_retry_at"]=(now()+timedelta(seconds=(10,30,120)[count])).isoformat()
        await self.ctx.db.write("log",[{"task_id":task["task_id"],"status":"needs_review" if ambiguous else "pending" if retry else "failed","params":jsonable(p),"result":jsonable(value),"error":{"code":type(exc).__name__,"retryable":retry},"step":"retry_wait" if retry else "failed"}],group_id=task["group_id"],mode="update",key_fields=("task_id",))
    async def loop(self):
        try:
            while not self.stopping:
                self.event.clear();task=await self.claim()
                if task:
                    try:await self.dispatch(task,self.ctx)
                    except asyncio.CancelledError:raise
                    except Exception as exc:
                        LOG.warning("task failed type=%s task=%s",type(exc).__name__,task["task_id"])
                        await self.fail(task,exc)
                else:
                    try:await asyncio.wait_for(self.event.wait(),1)
                    except TimeoutError:pass
        except Exception:
            self.ctx.ready=False;LOG.exception("worker stopped")
    async def stop(self):
        self.stopping=True;self.wake()
        if self.worker:
            try:await asyncio.wait_for(asyncio.shield(self.worker),30)
            except TimeoutError:
                self.worker.cancel()
                await asyncio.gather(self.worker,return_exceptions=True)
        if self.lease:await self.lease.close()
