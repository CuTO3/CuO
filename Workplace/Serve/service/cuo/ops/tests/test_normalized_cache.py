import json
from datetime import timedelta
from Core.cache import CacheManager
from Core.clock import now,business_date
from Function.summary.summary import run
from uuid import uuid4

async def test_normalized_cache_is_summary_source(ctx):
    instant=now();day=business_date(instant)
    await ctx.db.write('messages',[{'message_id':'777','sent_at':instant-timedelta(seconds=1),'business_date':day,'user_id':'123','nickname':'示例成员','text':'缓存里的讨论','segments':[]}],group_id=ctx.gid)
    ctx.cache=CacheManager(ctx.settings,ctx.db);ctx.db.set_cache(ctx.cache)
    await ctx.cache.refresh_day(ctx.gid,day)
    path=ctx.cache.paths(ctx.gid,day)['messages']
    row=json.loads(path.read_text(encoding='utf-8').strip())
    assert row['text']=='缓存里的讨论'
    assert not {'segments','processing','raw_event','received_at'}.intersection(row)
    original=ctx.db.read
    async def forbid_raw(table,**kwargs):
        if table=='messages':raise AssertionError('summary bypassed normalized cache')
        return await original(table,**kwargs)
    ctx.db.read=forbid_raw
    ctx.model.reply=json.dumps({'events':[{'title':'讨论','body':'记录讨论。','refs':[row['ref']],'quotes':[]}]},ensure_ascii=False)
    task=(await ctx.db.write('log',[{'task_id':str(uuid4()),'triggered_at':instant,'business_date':day,'request_type':'summary','params':{'request_text':'总结一下','snapshot_seq':1000}}],group_id=ctx.gid))[0]
    # Saving a summary does not mutate source messages and must not reread them.
    result=await run({**task,'group_id':ctx.gid},ctx)
    assert result['status']=='ok'
