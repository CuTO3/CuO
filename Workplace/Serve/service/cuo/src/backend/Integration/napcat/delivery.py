"""Durable action transitions. Ambiguous delivery requires reconciliation."""
import copy
from uuid import uuid4
from psycopg import sql
from Core.clock import now
from Core.results import jsonable
from Workflow._sender_ import prepare_actions,run as send
class RetryDelivery(RuntimeError):pass
async def persist(task,ctx,value,**state):
    await ctx.db.write("log",[{"task_id":task["task_id"],"result":jsonable(value),**state}],group_id=task["group_id"],mode="update",key_fields=("task_id",))
async def deliver(task,ctx,value):
    value=copy.deepcopy(value)
    if not value.get("delivery_prepared"):
        value["actions"]=await prepare_actions(task["group_id"],task["task_id"],value.get("actions",[]),context=ctx)
        value["delivery_prepared"]=True
        await persist(task,ctx,value,step="delivery_prepared")
    for action in value["actions"]:
        if action["status"]=="sent":continue
        if action["status"] in ("unknown","sending"):
            action["status"]="unknown"
            await persist(task,ctx,value,status="needs_review",step="delivery_unknown")
            return
        if action["status"]=="failed" and not (action.get("error") or {}).get("safe_to_retry"):
            await persist(task,ctx,value,status="failed",step="delivery_failed");return
        action["attempt"]+=1
        action["echo"]=str(task["task_id"])+":"+str(uuid4())
        action["status"]="sending"
        await persist(task,ctx,value,step="sending")
        response=await send(task["group_id"],task["task_id"],action,context=ctx)
        action.update(response)
        action["attempt_history"].append({"echo":action["echo"],"at":now().isoformat(),**response})
        await persist(task,ctx,value,step="delivery_"+action["status"])
        if action["status"]=="unknown":
            await persist(task,ctx,value,status="needs_review");return
        if action["status"]=="failed":
            if (action.get("error") or {}).get("safe_to_retry"):raise RetryDelivery()
            await persist(task,ctx,value,status="failed");return
    await persist(task,ctx,value,status="completed",step="completed",completed_at=now(),error=None)

async def reconcile(ctx,response):
    """Use exact persisted echo; receipt is never matched by message contents."""
    echo=response.get("echo")
    if not isinstance(echo,str):return
    for gid in ctx.db.groups:
        async with ctx.db.transaction(gid) as tx:
            rows=await ctx.db.fetch(gid,sql.SQL("SELECT * FROM {} WHERE result->'actions' @> %s::jsonb FOR UPDATE").format(ctx.db.table(gid,"log")),
                (__import__("json").dumps([{"echo":echo}]),),transaction=tx)
            for row in rows:
                value=row["result"];changed=False
                for action in value.get("actions",[]):
                    if action.get("echo")!=echo or action["status"] not in ("unknown","sending"):continue
                    # Active sender persists its own response; only late unknown receipts are reconciled.
                    if action["status"]=="sending":continue
                    from Workflow._sender_ import confirmed
                    if confirmed(action["type"],response):
                        action.update(status="sent",receipt=response.get("data") or {},error=None);changed=True
                if changed:
                    state="completed" if all(a["status"]=="sent" for a in value["actions"]) else "pending"
                    await ctx.db.write("log",[{"task_id":row["task_id"],"result":value,"status":state,"step":"late_receipt","completed_at":now() if state=="completed" else None}],group_id=gid,mode="update",key_fields=("task_id",),transaction=tx)
    if ctx.queue:ctx.queue.wake()
