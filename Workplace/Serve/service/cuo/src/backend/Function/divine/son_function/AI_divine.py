'''
本文件用途：根据聊天候选素材生成应事内容，使用专用 LiteLLM 虚拟 Key。

配置字段：
divine_ai_enabled                              启用应事 AI；关闭时使用固定应事内容
divine_ai_api_key                              此调用点专用的 LiteLLM 虚拟 Key
divine_ai_base_url                             LiteLLM 接口地址
divine_ai_model_name                           LiteLLM 中配置的模型名称
divine_ai_evidence_prompt_file                 应事提示词文件
divine_ai_request_attempt_limit                最多调用次数，包含第一次
divine_ai_request_timeout_seconds              单次调用总超时，包含请求等待
divine_ai_response_max_tokens                  模型输出 token 上限
divine_ai_advice_min_characters                应事内容最少字符数
divine_ai_advice_max_characters                应事内容最多字符数
'''

from Core.module_config import DivineAIConfig, load_module_config

DIVINE_AI_CONFIG = load_module_config(
    "src/backend/Function/divine/son_function/AI_divine_config.toml", DivineAIConfig
)

import asyncio,json
from types import SimpleNamespace
from Integration.litellm.client import ModelClient
from .readings import select_reading


def fallback(zhou):
    reading = zhou.get("reading") or select_reading(zhou)
    return {"keyword": "今日一应", "refs": [], "advice": reading["fallback_advice"]}

async def generate(zhou,tarot,dictum,candidates,luck_delta,ctx):
    reading=zhou.get("reading") or select_reading(zhou)
    if not candidates or not DIVINE_AI_CONFIG.divine_ai_enabled:return fallback(zhou)
    prompt=DIVINE_AI_CONFIG.divine_ai_evidence_prompt_file.read_text(encoding="utf-8")
    payload={"hexagram":zhou["base"]["name"],"tarot":tarot,"quote":dictum["primary"]["text_original"],"luck_delta":luck_delta,"candidates":candidates,"fixed_reading":reading}
    # 独立客户端只使用本调用点的 LiteLLM 配置；密钥不进入共享 Settings。
    settings=SimpleNamespace(
        model_base_url=DIVINE_AI_CONFIG.divine_ai_base_url,
        model_api_key=DIVINE_AI_CONFIG.divine_ai_api_key.get_secret_value(),
        model_name=DIVINE_AI_CONFIG.divine_ai_model_name,
        model_protocol="openai",
        model_timeout=DIVINE_AI_CONFIG.divine_ai_request_timeout_seconds,
    )
    client=ModelClient(settings)
    try:
        return await _generate_with_client(client,zhou,prompt,payload,candidates)
    finally:
        await client.close()


async def _generate_with_client(client,zhou,prompt,payload,candidates):
    for attempt in range(DIVINE_AI_CONFIG.divine_ai_request_attempt_limit):
        try:
            raw=await asyncio.wait_for(client.complete(messages=[{"role":"system","content":prompt},{"role":"user","content":json.dumps(payload,ensure_ascii=False)}],max_tokens=DIVINE_AI_CONFIG.divine_ai_response_max_tokens,response_format={"type":"json_object"}),DIVINE_AI_CONFIG.divine_ai_request_timeout_seconds)
            data=json.loads(raw)
            if not isinstance(data,dict) or set(data)!={"keyword","refs","advice"}:raise ValueError()
            if data=={"keyword":"今日一应","refs":[],"advice":""}:return fallback(zhou)
            matches=[c for c in candidates if c["keyword"]==data["keyword"]]
            if not matches or not isinstance(data["refs"],list) or not data["refs"] or any(r not in matches[0]["refs"] for r in data["refs"]):raise ValueError()
            if not isinstance(data["advice"],str) or not DIVINE_AI_CONFIG.divine_ai_advice_min_characters<=len(data["advice"])<=DIVINE_AI_CONFIG.divine_ai_advice_max_characters:raise ValueError()
            return data
        except (ValueError,TypeError,KeyError,RuntimeError,TimeoutError):pass
    return fallback(zhou)
