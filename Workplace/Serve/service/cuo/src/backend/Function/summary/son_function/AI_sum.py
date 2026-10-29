'''
本文件用途：Function/summary/son_function/AI_sum.py 的后端实现。

配置字段：
summary_text_ai_enabled                              启用此 AI 调用点
summary_text_ai_api_key                              此调用点专用 LiteLLM 虚拟 Key
summary_text_ai_base_url                             LiteLLM 接口地址
summary_text_ai_model_name                           LiteLLM 模型名称
summary_text_ai_request_timeout_seconds              单次请求超时（秒）
summary_text_ai_prompt_file                          总结提示词文件
summary_text_chunk_character_limit                   每批消息序列化字符上限
summary_text_batch_timeout_seconds                   每批总超时
summary_text_ai_request_attempt_limit                最多尝试次数
summary_text_ai_response_max_tokens                  输出 token 上限
'''

from Core.configuration import load, resource

CONFIG = load("summary_text")
from Integration.litellm.callsite import CallsiteModel
MODEL = CallsiteModel(CONFIG, 'summary_text_ai')

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
    prompt=resource(CONFIG["summary_text_ai_prompt_file"]).read_text(encoding="utf-8")
    chunks=[];current=[];size=0
    for row in records:
        length=len(json.dumps(row,ensure_ascii=False))
        if length>CONFIG["summary_text_chunk_character_limit"]:raise SummaryError("message exceeds budget")
        if size+length>CONFIG["summary_text_chunk_character_limit"] and current:chunks.append(current);current=[];size=0
        current.append(row);size+=length
    if current:chunks.append(current)
    events=[]
    # Bound each batch independently: a busy day must not exhaust a shared deadline.
    # Sequential calls retain the provider's existing single-request concurrency.
    for chunk in chunks:
        async with asyncio.timeout(CONFIG["summary_text_batch_timeout_seconds"]):
            error=None
            for attempt in range(CONFIG["summary_text_ai_request_attempt_limit"]):
                raw=await MODEL.complete(messages=[{"role":"system","content":prompt},{"role":"user","content":json.dumps({"scope":scope,"records":chunk,"repair":error},ensure_ascii=False)}],max_tokens=CONFIG["summary_text_ai_response_max_tokens"],response_format={"type":"json_object"})
                try:events.extend(validate(parse_json(raw),chunk));break
                except (ValueError,TypeError,KeyError) as exc:
                    error=type(exc).__name__
                    if attempt == CONFIG["summary_text_ai_request_attempt_limit"] - 1:raise SummaryError("evidence validation failed") from None
    return events
