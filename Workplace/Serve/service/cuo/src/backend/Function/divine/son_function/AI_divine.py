import asyncio,json
from pathlib import Path
FALLBACK={"keyword":"今日小事","refs":[],"advice":"今天给自己留点空闲，吃顿热乎的再出门；小事慢慢来，别急着跟运气较劲。"}
async def generate(zhou,tarot,dictum,candidates,luck_delta,ctx):
    if not candidates:return dict(FALLBACK)
    prompt=(Path(__file__).parents[1]/"prompts/divine_prompt.txt").read_text(encoding="utf-8")
    payload={"hexagram":zhou["base"]["name"],"tarot":tarot,"quote":dictum["primary"]["text_original"],"luck_delta":luck_delta,"candidates":candidates}
    for attempt in range(2):
        try:
            raw=await asyncio.wait_for(ctx.model.complete(messages=[{"role":"system","content":prompt},{"role":"user","content":json.dumps(payload,ensure_ascii=False)}],max_tokens=700,response_format={"type":"json_object"}),30)
            data=json.loads(raw)
            if not isinstance(data,dict) or set(data)!={"keyword","refs","advice"}:raise ValueError()
            matches=[c for c in candidates if c["keyword"]==data["keyword"]]
            if not matches or not isinstance(data["refs"],list) or not data["refs"] or any(r not in matches[0]["refs"] for r in data["refs"]):raise ValueError()
            if not isinstance(data["advice"],str) or not 15<=len(data["advice"])<=100:raise ValueError()
            return data
        except (ValueError,TypeError,KeyError,RuntimeError,TimeoutError):pass
    return dict(FALLBACK)
