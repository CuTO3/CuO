'''
本文件用途：Model API adapter; supports LiteLLM and the existing provider during migration.

配置字段：
model_api_key                        模型接口密钥
model_base_url                       模型接口地址
model_name                           模型名称
model_protocol                       模型接口协议
model_timeout                        模型客户端超时（秒）
vision_api_key                       图片识别接口密钥
vision_base_url                      图片识别接口地址
vision_model_name                    图片识别模型名称
'''

import asyncio
import httpx
class ModelUnavailable(RuntimeError):
    pass
class ModelClient:
    def __init__(self,settings):
        self.settings=settings
        self.last_usage={}
        self.client=httpx.AsyncClient(timeout=settings.model_timeout)
        self.lock=asyncio.Semaphore(1)
    async def complete(self,*,messages,temperature=.7,max_tokens=4096,response_format=None):
        s=self.settings
        if not s.model_api_key: raise ModelUnavailable("text model not configured")
        base=s.model_base_url.rstrip("/")
        if not base.endswith("/v1"): base+="/v1"
        body={"model":s.model_name,"messages":messages,"max_tokens":max_tokens,"temperature":temperature}
        if s.model_protocol=="anthropic":
            body["system"]="\n".join(m["content"] for m in messages if m["role"]=="system")
            body["messages"]=[m for m in messages if m["role"]!="system"]
            headers={"x-api-key":s.model_api_key,"anthropic-version":"2023-06-01"}
            endpoint=base+"/messages"
        else:
            headers={"Authorization":"Bearer "+s.model_api_key}
            endpoint=base+"/chat/completions"
            if response_format:
                body["response_format"]=response_format
                body["thinking"]={"type":"disabled"}
                # LiteLLM drops unsupported top-level OpenAI parameters.
                # extra_body forwards this provider option through the gateway.
                body["extra_body"]={"thinking":{"type":"disabled"}}
        async with self.lock:
            try:
                r=await self.client.post(endpoint,headers=headers,json=body)
                r.raise_for_status(); data=r.json()
                self.last_usage=data.get("usage",{})
                text=("\n".join(b.get("text","") for b in data.get("content",[]) if b.get("type")=="text")
                      if s.model_protocol=="anthropic" else data["choices"][0]["message"]["content"])
                if not isinstance(text,str) or not text.strip(): raise ValueError("empty response")
                return text
            except (httpx.HTTPError,ValueError,KeyError,TypeError,IndexError):
                raise ModelUnavailable("model request failed") from None
    async def describe_images(self,images,prompt):
        s=self.settings
        if not all((s.vision_base_url,s.vision_api_key,s.vision_model_name)):
            raise ModelUnavailable("vision model not configured")
        base=s.vision_base_url.rstrip("/")
        if not base.endswith("/v1"): base+="/v1"
        content=[{"type":"text","text":prompt}]+[{"type":"image_url","image_url":{"url":image}} for image in images]
        try:
            r=await self.client.post(base+"/chat/completions",headers={"Authorization":"Bearer "+s.vision_api_key},
                json={"model":s.vision_model_name,"messages":[{"role":"user","content":content}],"max_tokens":1000})
            r.raise_for_status()
            text=r.json()["choices"][0]["message"]["content"]
            if not isinstance(text,str) or not text.strip(): raise ValueError()
            return text
        except (httpx.HTTPError,ValueError,KeyError,TypeError,IndexError):
            raise ModelUnavailable("vision request failed") from None
    async def close(self):
        await self.client.aclose()
