from __future__ import annotations

import asyncio
import httpx


class ModelUnavailable(RuntimeError):
    pass


class ModelClient:
    def __init__(self, settings):
        self.settings = settings
        self.last_usage = {}
        self._client = httpx.AsyncClient(timeout=settings.model_timeout)
        self._semaphore = asyncio.Semaphore(settings.model_concurrency)

    async def complete(self, *, messages, temperature=0.7, max_tokens=4096, response_format=None):
        if not self.settings.model_api_key:
            raise ModelUnavailable("MODEL_API_KEY is not configured")
        base = self.settings.model_base_url.rstrip("/")
        body = {"model": self.settings.model_name, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if self.settings.model_protocol == "anthropic":
            system = "\n".join(item["content"] for item in messages if item["role"] == "system")
            body["messages"] = [item for item in messages if item["role"] != "system"]
            body["system"] = system
            endpoint = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
            headers = {"x-api-key": self.settings.model_api_key, "anthropic-version": "2023-06-01"}
        else:
            endpoint = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
            headers = {"Authorization": "Bearer " + self.settings.model_api_key}
            if response_format is not None:
                body["response_format"] = response_format
        async with self._semaphore:
            try:
                response = await self._client.post(endpoint, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
                self.last_usage = data.get("usage", {})
                if self.settings.model_protocol == "anthropic":
                    text = "\n".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
                else:
                    text = data["choices"][0]["message"]["content"]
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("empty model response")
                return text
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                raise ModelUnavailable("model request failed: " + type(exc).__name__) from None

    async def close(self):
        await self._client.aclose()
