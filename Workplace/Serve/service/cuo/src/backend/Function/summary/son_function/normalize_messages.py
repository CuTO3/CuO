'''
本文件用途：Function/summary/son_function/normalize_messages.py 的后端实现。

配置字段：
未检测到直接读取共享 Settings 或环境变量；局部参数与间接依赖仍需逐项核查。
'''

import re,regex
from .image_processor import segment_key
def clean(text):return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]","",str(text)).replace("\r\n","\n")
async def normalize_messages(rows,ctx,group_id,include_divine=False):
    gid=ctx.db.check_group(group_id)
    configured={m["user_id"]:m for m in await ctx.db.read("members",group_id=gid,filters={})}
    names={};used={}
    for uid in sorted({r["user_id"] for r in rows}|set(configured)):
        m=configured.get(uid,{})
        nickname=next((r.get("nickname","") for r in reversed(rows) if r["user_id"]==uid),"")
        name=m.get("display_name") or "".join(regex.findall(r"\X",nickname or m.get("nickname",""))[:4]) or "群友"
        used[name]=used.get(name,0)+1;names[uid]=name+(str(used[name]) if used[name]>1 else "")
    kept=[r for r in rows if not (r.get("generated_by") in ("summary","divine") and not include_divine)]
    refs={r["message_id"]:"m"+str(i+1).zfill(5) for i,r in enumerate(kept)}
    mapping={refs[r["message_id"]]:{"message_id":r["message_id"],"user_id":r["user_id"]} for r in kept}
    records=[]
    for row in kept:
        mentions=[];reply=None;media=[];parts=[]
        for seg in row.get("segments",[]):
            kind=seg.get("type");data=seg.get("data",{})
            if kind=="text":parts.append(clean(data.get("text","")))
            elif kind=="at":
                uid=str(data.get("qq",""));name="全体成员" if uid=="all" else names.get(uid,"群友")
                mentions.append(name);parts.append("@"+name)
            elif kind=="reply":
                target=str(data.get("id",""))
                if target in refs:reply={"ref":refs[target]}
                else:
                    ext=await ctx.db.read("messages",group_id=gid,filters={"message_id":target},limit=1)
                    reply={"context_only":True,"speaker":names.get(ext[0]["user_id"],"群友"),"text":clean(ext[0]["text"])[:200]} if ext else {"unavailable":True}
            elif kind=="image":
                cached=row.get("processing",{}).get("media_descriptions",{}).get(segment_key(seg),{})
                description=cached.get("description","图片尚未识别")
                media.append({"type":"image","description":description,"status":cached.get("status","pending")})
                parts.append("[图片："+description+"]")
            elif kind=="face":parts.append("[QQ表情："+str(data.get("name") or data.get("id","未知"))+"]")
            else:parts.append("["+str(kind)+"]")
        text="".join(parts) if row.get("segments") else clean(row["text"])
        if text.strip():records.append({"ref":refs[row["message_id"]],"time":row["sent_at"].isoformat(),"speaker":names[row["user_id"]],"text":text,"mentions":mentions,"reply_to":reply,"media":media,"kind":"bot" if row.get("generated_by") else "human"})
    return records,mapping
