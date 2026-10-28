"""Persist randomness before model work; settle account and result in one transaction."""
import json,math,secrets
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
import jieba.posseg
from psycopg import sql

from Core.clock import business_date,now
from Core.results import result,save,saved
from Function.summary.son_function.normalize_messages import normalize_messages

from .son_function.zhou_yi import cast
from .son_function.tarot import map_tarot
from .son_function.AI_divine import generate
from .son_function.merge_message import render
from .son_function.tarot_image import message_action
from .son_function.luck import assess_dictum
from .son_function.readings import select_reading

DATA=Path(__file__).parent/"data"

def luck_weights():
    b=lambda x:math.exp(-x*x/18)
    flat=sum(b(x) for x in (1,2,3))/3
    return [b(5) if x==0 else flat if 1<=abs(x)<=3 else b(x) for x in range(-10,11)]
def draw_luck(rng=None):
    rng=rng or secrets.SystemRandom();weights=luck_weights();total=sum(weights);u=rng.random();c=0
    if not 0<=u<1:raise ValueError("invalid random draw")
    for x,w in zip(range(-10,11),weights):
        c+=w/total
        if u<c or x==10:return x

def draw_dictum_luck(dictum,rng=None):
    assessment=dictum.get("reading_fortune") or assess_dictum(dictum)
    direction=assessment["direction"]
    if not direction:return 0
    magnitude=min(assessment["magnitude_max"],max(assessment["magnitude_min"],abs(draw_luck(rng))))
    return direction*magnitude

def candidates_from(records,ref_map,uid):
    rules=json.loads((DATA/"keyword_rules.json").read_text(encoding="utf-8"))
    found={}
    for row in records:
        text=row["text"]
        if row["kind"]=="bot" or any(s in text for s in rules["excluded"]):continue
        phrases=[p for p in sorted(rules["phrases"],key=len,reverse=True) if p in text]
        if not phrases:phrases=[p.word for p in jieba.posseg.cut(text) if p.flag.startswith("n") and 2<=len(p.word)<=12 and p.word not in rules["stopwords"]][:8]
        own=ref_map[row["ref"]]["user_id"]==uid
        reply=(row.get("reply_to") or {}).get("ref")
        responds=reply in ref_map and ref_map[reply]["user_id"]==uid
        for word in set(phrases):
            c=found.setdefault(word,{"keyword":word,"refs":[],"speaker_relation":"group","source_excerpt":[],"score":0,"speakers":set(),"last":""})
            if row["ref"] in c["refs"]:continue
            c["refs"].append(row["ref"]);c["score"]+=4*own+2*responds+2*any(s in text for s in ("失败","没出","连跪"))
            c["speakers"].add(ref_map[row["ref"]]["user_id"]);c["last"]=max(c["last"],row["time"])
            if own:c["speaker_relation"]="self"
            elif responds and c["speaker_relation"]!="self":c["speaker_relation"]="reply"
            if len(c["source_excerpt"])<4:c["source_excerpt"].append({"ref":row["ref"],"text":text[:200]+("…[截断]" if len(text)>200 else "")})
    for c in found.values():c["score"]+=min(len(c.pop("speakers")),3)
    selected=sorted(found.values(),key=lambda c:c["keyword"])
    selected.sort(key=lambda c:c["last"],reverse=True);selected.sort(key=lambda c:c["score"],reverse=True)
    return selected[:5]

async def run(task,ctx):
    old=await saved(task,ctx)
    if old is not None:return old
    gid=ctx.db.check_group(task["group_id"]);uid=task["user_id"];day=business_date(task["triggered_at"])
    async with ctx.db.transaction(gid) as tx:
        await ctx.db.fetch(gid,"SELECT pg_advisory_xact_lock(hashtextextended(%s, 43))",(gid+":"+uid+":"+str(day),),transaction=tx)
        rows=await ctx.db.read("divinations",group_id=gid,filters={"user_id":uid,"business_date":day},order_by=(("created_at","desc"),("id","desc")),transaction=tx)
        draft=next((r for r in rows if str(r["task_id"])==str(task["task_id"])),None)
        if draft is None:
            if any(r["status"]=="generating" for r in rows):
                return await save(task,ctx,result("skipped",actions=[{"type":"send_message","text":"这卦还在算，稍等一下喵。"}],error_code="divination_pending"),tx=tx)
            latest=next((r for r in rows if r["status"]=="settled"),None)
            cost=2 if latest else 0
            if cost:
                members=await ctx.db.fetch(gid,sql.SQL("SELECT * FROM {} WHERE user_id=%s FOR UPDATE").format(ctx.db.table(gid,"members")),(uid,),transaction=tx)
                fortune=members[0]["fortune"]
                if fortune<cost:
                    actions=[{"type":"send_message","text":"今日缘法已尽，且待明日再问。"},message_action(latest["content"],latest["tarot"])]
                    return await save(task,ctx,result("skipped",actions=actions,result_id=latest["id"],error_code="insufficient_fortune"),tx=tx)
            zhou=cast();reading=select_reading(zhou)
            dictum={"primary":reading["primary"],"auxiliary":reading["auxiliary"],"rule_version":reading["version"],"reading_fortune":reading["fortune"]}
            delta=draw_dictum_luck(dictum)
            zhou["reading"]=reading
            zhou["luck_version"]=reading["version"];zhou["luck_judgment"]=reading["fortune"]
            zhou["snapshot_seq"]=task["params"].get("snapshot_seq",task["params"].get("message_row_id"))
            zhou["repeat_cost"]=cost
            if type(zhou["snapshot_seq"]) is not int:raise ValueError("snapshot required")
            if cost:
                await ctx.db.write("members",[{"user_id":uid,"fortune":fortune-cost,"updated_at":now()}],group_id=gid,mode="update",key_fields=("user_id",),transaction=tx)
            draft=(await ctx.db.write("divinations",[{"id":str(uuid4()),"task_id":task["task_id"],"user_id":uid,"business_date":day,"zhou_yi":zhou,"tarot":map_tarot(zhou,delta),"dictum":dictum,"luck_delta":delta}],group_id=gid,transaction=tx))[0]
    if draft["status"]=="settled":
        return await save(task,ctx,result(result_id=draft["id"],actions=[message_action(draft["content"],draft["tarot"])]))
    zhou=draft["zhou_yi"]
    if "ai_result" not in zhou:
        rows=await ctx.db.read("messages",group_id=gid,filters={"business_date":day-timedelta(days=1),"id":{"lte":zhou["snapshot_seq"]}},order_by=(("sent_at","asc"),("id","asc")))
        rows=[r for r in rows if not r.get("generated_by") and not r.get("processing",{}).get("receiver",{}).get("at_bot")]
        records,mapping=await normalize_messages(rows,ctx,gid)
        candidates=candidates_from(records,mapping,uid)
        zhou["ai_result"]=await generate(zhou,draft["tarot"],draft["dictum"],candidates,draft["luck_delta"],ctx)
        zhou["candidates"]=candidates
        await ctx.db.write("divinations",[{"id":draft["id"],"zhou_yi":zhou}],group_id=gid,mode="update",key_fields=("id",))
    async with ctx.db.transaction(gid) as tx:
        rows=await ctx.db.fetch(gid,sql.SQL("SELECT * FROM {} WHERE id=%s FOR UPDATE").format(ctx.db.table(gid,"divinations")),(draft["id"],),transaction=tx)
        locked=rows[0]
        if locked["status"]=="settled":return await save(task,ctx,result(result_id=locked["id"],actions=[message_action(locked["content"],locked["tarot"]) ]),tx=tx)
        members=await ctx.db.fetch(gid,sql.SQL("SELECT * FROM {} WHERE user_id=%s FOR UPDATE").format(ctx.db.table(gid,"members")),(uid,),transaction=tx)
        before=members[0]["fortune"];after=before+draft["luck_delta"];ai=zhou["ai_result"]
        content=render(zhou,draft["tarot"],ai,draft["luck_delta"],after)
        if zhou.get("repeat_cost"):
            content="往日福缘深厚，尚可再问天机。\n\n"+content
        await ctx.db.write("members",[{"user_id":uid,"fortune":after,"updated_at":now()}],group_id=gid,mode="update",key_fields=("user_id",),transaction=tx)
        await ctx.db.write("divinations",[{"id":draft["id"],"status":"settled","keyword":ai["keyword"],"advice":ai["advice"],"fortune_before":before,"fortune_after":after,"content":content,"settled_at":now()}],group_id=gid,mode="update",key_fields=("id",),transaction=tx)
        return await save(task,ctx,result(result_id=draft["id"],actions=[message_action(content,draft["tarot"])]),tx=tx)
