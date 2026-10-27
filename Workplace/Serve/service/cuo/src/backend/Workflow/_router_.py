"""Select and execute the business handler for a classified durable task."""
from Core import archive
from Core.results import result, save
from Integration.console.admin import execute
ERRORS={"multiple_intents":"要求太多啦，一次说一件事。","empty_input":"叫我做什么？说句话吧。","invalid_date":"是今天还是明天啊，我怎么看不明白吖","unsupported_date":"是今天还是明天啊，我怎么看不明白吖","future_date":"嗯...还没到那一天嘛，我不是占卜师喵","unsupported_intent":"还没做完QAQ","intention_failed":"听不懂喵","invalid_request":"你说的是啥喵"}
async def route(task,ctx,kind):
    from Function.conversation import conversation
    from Function.memento import memento
    from Function.summary import summary
    from Function.divine import divine
    from Function.summary.son_function import image_processor
    if kind=="error":
        code=task["params"].get("code")
        return await save(task,ctx,result("error",error_code=code,actions=[{"type":"send_message","text":ERRORS.get(code,ERRORS["invalid_request"])}]))
    handlers={"conversation":conversation.run,"memento":memento.run,"summary":summary.run,"divine":divine.run,"media_describe":image_processor.run,"archive_day":archive.run,"initialize_day":archive.run,"admin_update":execute}
    if kind not in handlers:raise ValueError("unsupported task type")
    value=await handlers[kind](task,ctx)
    rows=await ctx.db.read("log",group_id=task["group_id"],filters={"task_id":task["task_id"]},limit=1)
    if rows[0]["business_status"]!="completed":
        if value.get("status")=="error":
            await ctx.db.write("log",[{"task_id":task["task_id"],"status":"needs_review","step":value.get("error_code") or "business_review","error":{"code":value.get("error_code")}}],group_id=task["group_id"],mode="update",key_fields=("task_id",))
            return None
        await save(task,ctx,value)
    return value
