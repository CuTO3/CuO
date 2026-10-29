'''
本文件用途：Authenticated reads and version-checked mutations through the worker.

配置字段：
admin_token                          控制台访问凭据
'''

import hashlib,hmac,json
from uuid import uuid4
from fastapi import Request,HTTPException
from Core.clock import now,business_date
from Core.results import jsonable,result,save
from psycopg import sql
TABLES={"members","log","summaries","divinations","messages"}
MAX_SAFE_FORTUNE=9007199254740991
def version(row):
    return hashlib.sha256(json.dumps(jsonable(row),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def install(app):
    def auth(request):
        from Integration.console.routes import authenticated
        if authenticated(request):return request.app.state.ctx
        token=request.app.state.ctx.settings.admin_token
        if not token or not hmac.compare_digest(request.headers.get("authorization",""),"Bearer "+token):raise HTTPException(401,"administrator authentication required")
        return request.app.state.ctx
    @app.get("/admin/groups")
    async def groups(request:Request):
        ctx=auth(request)
        return {"groups":sorted(ctx.db.groups),"corpus_conflict":getattr(ctx,"corpus_conflict",False)}
    @app.get("/admin/{gid}/{table}")
    async def read(gid:str,table:str,request:Request,limit:int=100):
        ctx=auth(request)
        if gid not in ctx.db.groups or table not in TABLES:raise HTTPException(404)
        if not 1<=limit<=500:raise HTTPException(422)
        order="updated_at" if table=="members" else "sent_at" if table=="messages" else "created_at"
        rows=await ctx.db.read(table,group_id=gid,filters={},order_by=((order,"desc"),),limit=limit)
        return [{"version":version(r),"record":jsonable(r)} for r in rows]
    @app.post("/admin/{gid}/commands",status_code=202)
    async def command(gid:str,request:Request):
        ctx=auth(request)
        if gid not in ctx.db.groups:raise HTTPException(404)
        body=await request.body()
        if len(body)>16384:raise HTTPException(413)
        try:
            p=json.loads(body)
            if not isinstance(p,dict) or p.get("operation") not in {"display_name","fortune","retry","resolve_delivery","nickname_slots"} or not isinstance(p.get("expected_version"),str):raise ValueError()
            if p["operation"]=="display_name":
                if not isinstance(p.get("user_id"),str) or p.get("display_name") is not None and (not isinstance(p["display_name"],str) or len(p["display_name"])>100):raise ValueError()
            elif p["operation"]=="fortune":
                if set(p)!={"operation","user_id","fortune","expected_version"} or not isinstance(p.get("user_id"),str) or not p["user_id"].isascii() or not p["user_id"].isdecimal():raise ValueError()
                if type(p.get("fortune")) is not int or abs(p["fortune"])>MAX_SAFE_FORTUNE:raise ValueError()
            else:
                from uuid import UUID
                UUID(p["target_task_id"])
        except (ValueError,KeyError,TypeError):raise HTTPException(422,"invalid command") from None
        instant=now();tid=str(uuid4())
        await ctx.db.write("log",[{"task_id":tid,"triggered_at":instant,"business_date":business_date(instant),"request_type":"admin_update","params":p}],group_id=gid)
        ctx.queue.wake();return {"task_id":tid}
    @app.get("/admin/{gid}/commands/{task_id}")
    async def command_status(gid:str,task_id:str,request:Request):
        ctx=auth(request)
        if gid not in ctx.db.groups:raise HTTPException(404)
        from uuid import UUID
        try:UUID(task_id)
        except ValueError:raise HTTPException(422,"invalid task id") from None
        rows=await ctx.db.read("log",group_id=gid,filters={"task_id":task_id,"request_type":"admin_update"},limit=1)
        if not rows:raise HTTPException(404)
        return {"version":version(rows[0]),"record":jsonable(rows[0])}

async def execute(task,ctx):
    p=task["params"];op=p["operation"];gid=task["group_id"]
    table="members" if op in {"display_name","fortune"} else "log";key="user_id" if table=="members" else "task_id"
    target=p["user_id"] if table=="members" else p["target_task_id"]
    async with ctx.db.transaction(gid) as tx:
        rows=await ctx.db.fetch(gid,sql.SQL("SELECT * FROM {} WHERE {}=%s FOR UPDATE").format(ctx.db.table(gid,table),sql.Identifier(key)),(target,),transaction=tx)
        if not rows or version(rows[0])!=p["expected_version"]:
            return await save(task,ctx,result("error",error_code="version_conflict"),tx=tx)
        row=rows[0];update={key:target}
        if op=="display_name":
            update.update(display_name=p["display_name"],updated_at=now())
        elif op=="fortune":
            if type(p.get("fortune")) is not int or abs(p["fortune"])>MAX_SAFE_FORTUNE:raise ValueError("invalid fortune")
            update.update(fortune=p["fortune"],updated_at=now())
        elif op=="retry":
            if row["status"] not in ("failed","needs_review"):raise ValueError("task is not retryable")
            if any(a.get("status") in ("sending","unknown") for a in row["result"].get("actions",[])):raise ValueError("resolve unknown delivery first")
            params=row["params"];params.pop("_retry_at",None);params["_retry_count"]=0
            update.update(status="pending",params=params,error=None)
        elif op=="nickname_slots":
            if row["request_type"]!="memento" or row["business_status"]=="completed":raise ValueError("not a pending memento")
            slots=p.get("slots")
            if not isinstance(slots,list) or len(slots)!=6 or any(x is not None and (not isinstance(x,str) or not x) for x in slots) or "".join(x or "" for x in slots)!=row["params"]["new_nickname"]:raise ValueError("invalid slots")
            params={**row["params"],"manual_slots":slots};params.pop("_retry_at",None)
            update.update(status="pending",params=params,error=None)
        elif op=="resolve_delivery":
            value=row["result"];action=next((a for a in value.get("actions",[]) if a["action_id"]==p.get("action_id")),None)
            if action is None or action["status"] not in ("unknown","failed"):raise ValueError("no unresolved action")
            decision=p.get("decision")
            if decision not in ("confirm_sent","resend"):raise ValueError("explicit delivery decision required")
            action["attempt_history"].append({"admin_task":str(task["task_id"]),"decision":decision,"previous_status":action["status"],"at":now().isoformat()})
            action["status"]="sent" if decision=="confirm_sent" else "pending"
            action["error"]=None
            update.update(result=value,status="pending",error=None)
        await ctx.db.write(table,[update],group_id=gid,mode="update",key_fields=(key,),transaction=tx)
        metadata={"fortune_before":row["fortune"],"fortune_after":p["fortune"]} if op=="fortune" else {}
        return await save(task,ctx,result(target=str(target),operation=op,**metadata),tx=tx)
