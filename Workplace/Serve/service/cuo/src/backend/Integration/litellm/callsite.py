'''
本文件用途：按调用点的小配置访问 LiteLLM，专用 Key 由 LiteLLM 统计用量。

配置字段：
各调用点_ai_enabled                    是否启用调用点
各调用点_ai_api_key                    专用 LiteLLM 虚拟 Key
各调用点_ai_base_url                   LiteLLM 地址
各调用点_ai_model_name                 LiteLLM 模型名称
各调用点_ai_request_timeout_seconds    请求超时（秒）
'''

from types import SimpleNamespace
from Integration.litellm.client import ModelClient, ModelUnavailable


class CallsiteModel:
    def __init__(self, values, prefix):
        self.values = values
        self.prefix = prefix

    @property
    def model_name(self):
        return self.values[self.prefix + '_model_name']

    def _client(self):
        v, p = self.values, self.prefix
        if not v[p + '_enabled']:
            raise ModelUnavailable('AI callsite disabled')
        return ModelClient(SimpleNamespace(
            model_base_url=v[p + '_base_url'], model_api_key=v[p + '_api_key'],
            model_name=v[p + '_model_name'], model_protocol='openai',
            model_timeout=v[p + '_request_timeout_seconds'],
            vision_base_url=v[p + '_base_url'], vision_api_key=v[p + '_api_key'],
            vision_model_name=v[p + '_model_name'],
        ))

    async def complete(self, **kwargs):
        client = self._client()
        try:
            return await client.complete(**kwargs)
        finally:
            await client.close()

    async def describe_images(self, images, prompt):
        client = self._client()
        try:
            return await client.describe_images(images, prompt)
        finally:
            await client.close()
