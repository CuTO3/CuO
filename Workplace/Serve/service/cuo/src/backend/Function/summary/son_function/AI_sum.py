import asyncio,json
from pathlib import Path
class SummaryError(ValueError):pass
def parse_json(raw):
    raw=raw.strip();fence=chr(96)*3
    if raw.startswith(fence):raw=raw.split("\n",1)[1].rsplit(fence,1)[0]
    return json.loads(raw)
def validate(data,records):
    refs={r["ref"]:r for r in records}
    if not isinstance(data,dict) or set(data)!={"events"} or not isinstance(data["events"],list):raise SummaryError("invalid events")
    for e in data["events"]:
        if not isinstance(e,dict) or set(e)!={"title","body","refs","quotes"}:raise SummaryError("invalid event")
        if any(not isinstance(e[k],str) or not e[k].strip() for k in ("title","body")):raise SummaryError("empty event")
        if not isinstance(e["refs"],list) or not e["refs"] or any(r not in refs for r in e["refs"]):raise SummaryError("invalid evidence")
        if not isinstance(e["quotes"],list):raise SummaryError("invalid quotes")
        for q in e["quotes"]:
            if not isinstance(q,dict) or set(q)!={"ref","text"} or q["ref"] not in e["refs"] or not isinstance(q["text"],str) or not q["text"] or q["text"] not in refs[q["ref"]]["text"]:raise SummaryError("invented quote")
        if any(r in e["title"]+e["body"] for r in refs):raise SummaryError("ref exposed")
    return data["events"]
async def generate(records,scope,ctx):
    prompt=(Path(__file__).parents[1]/"prompts/summary_prompt.txt").read_text(encoding="utf-8")
    chunks=[];current=[];size=0
    for row in records:
        length=len(json.dumps(row,ensure_ascii=False))
        if length>12000:raise SummaryError("message exceeds budget")
        if size+length>12000 and current:chunks.append(current);current=[];size=0
        current.append(row);size+=length
    if current:chunks.append(current)
    events=[]
    # Bound each batch independently: a busy day must not exhaust a shared deadline.
    # Sequential calls retain the provider's existing single-request concurrency.
    for chunk in chunks:
        async with asyncio.timeout(120):
            error=None
            for attempt in range(2):
                raw=await ctx.model.complete(messages=[{"role":"system","content":prompt},{"role":"user","content":json.dumps({"scope":scope,"records":chunk,"repair":error},ensure_ascii=False)}],max_tokens=5000,response_format={"type":"json_object"})
                try:events.extend(validate(parse_json(raw),chunk));break
                except (ValueError,TypeError,KeyError) as exc:
                    error=type(exc).__name__
                    if attempt:raise SummaryError("evidence validation failed") from None
    return events
