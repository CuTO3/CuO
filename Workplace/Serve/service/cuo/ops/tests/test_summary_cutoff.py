"""Real PostgreSQL regression cases for OneBot's second-precision timestamps."""
import json
from datetime import datetime,timedelta
from uuid import uuid4
import pytest
from Core.clock import BEIJING,business_date,day_bounds
from Function.summary.summary import run

@pytest.mark.parametrize("historical", [False, True])
async def test_cutoff_uses_timestamp_and_intake_sequence(ctx,historical):
    cutoff=datetime(2026,10,26,22,26,34,tzinfo=BEIJING)
    day=business_date(cutoff)-timedelta(days=1 if historical else 0)
    start,day_end=day_bounds(day)
    captured=[]
    async def fake_complete(**kwargs):
        records=json.loads(kwargs["messages"][-1]["content"])["records"]
        captured.extend(records)
        return json.dumps({"events":[{"title":"测试话题","body":"记录了讨论内容。",
            "refs":[records[0]["ref"]],"quotes":[]} ]})
    ctx.model.complete=fake_complete
    async def message(mid,instant,text):
        return (await ctx.db.write("messages",[{"message_id":str(mid),"sent_at":instant,
            "business_date":business_date(instant),"user_id":"123","nickname":"群友",
            "text":text,"segments":[]}],group_id=ctx.gid))[0]

    await message(1,start-timedelta(seconds=1),"上一业务日应排除")
    await message(2,start,"当天起点应包含")
    await message(3,day_end-timedelta(seconds=1) if historical else cutoff,"同秒先到应包含")
    # A bad/future event timestamp must not enter the summary even with a low id.
    await message(4,day_end if historical else cutoff+timedelta(seconds=1),"时间越界应排除")
    command=await message(5,cutoff,"总结命令本身应排除")
    await message(6,cutoff,"同秒后到应排除")
    await message(7,start+timedelta(seconds=1),"晚到旧时间消息应排除")

    task=(await ctx.db.write("log",[{"task_id":str(uuid4()),"triggered_at":cutoff,
        "business_date":business_date(cutoff),"request_type":"summary","user_id":"123",
        "message_id":command["message_id"],"params":{"target_date":str(day),
        "request_text":"总结一下","snapshot_seq":command["id"]}}],group_id=ctx.gid))[0]
    value=await run({**task,"group_id":ctx.gid},ctx)
    assert value["status"]=="ok"
    assert [r["text"] for r in captured]==["当天起点应包含","同秒先到应包含"]
    row=(await ctx.db.read("summaries",group_id=ctx.gid,filters={"id":value["result_id"]}))[0]
    assert row["end_at"]==(day_end if historical else cutoff)
    expected_end=day_end if historical else cutoff
    assert f"{start:%m-%d %H:%M}—{expected_end:%m-%d %H:%M}" in row['content']
