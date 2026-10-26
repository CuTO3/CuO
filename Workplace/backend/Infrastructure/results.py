import json
from datetime import date,datetime
from uuid import UUID
def jsonable(value):
    return json.loads(json.dumps(value,ensure_ascii=False,default=lambda x:x.isoformat() if isinstance(x,(date,datetime)) else str(x) if isinstance(x,UUID) else (_ for _ in ()).throw(TypeError(type(x).__name__))))
def result(status="ok",actions=None,result_id=None,error_code=None,**metadata):
    return {"status":status,"actions":actions or [],"result_id":str(result_id) if result_id else None,"error_code":error_code,**metadata}
async def save(task,ctx,value,*,tx=None):
    await ctx.db.write("log",[{"task_id":task["task_id"],"result":jsonable(value),"business_status":"completed","step":"business_completed"}],
        group_id=task["group_id"],mode="update",key_fields=("task_id",),transaction=tx)
    return value
async def saved(task,ctx):
    rows=await ctx.db.read("log",group_id=task["group_id"],filters={"task_id":task["task_id"]},limit=1)
    if not rows: raise ValueError("task not found")
    return rows[0]["result"] if rows[0]["business_status"]=="completed" else None
