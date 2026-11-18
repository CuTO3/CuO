from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from Function.conversation import conversation
from Function.summary.son_function.image_processor import segment_key
from Workflow._analyzer_ import classify_task


async def test_conversation_sends_current_image_and_media_only_history(monkeypatch):
    image = {"type": "image", "data": {"url": "https://example.invalid/image"}}
    image_description = {"status": "ready", "description": "一只蓝鲸"}
    current = {
        "segments": [{"type": "at", "data": {"qq": "999"}}, image],
        "processing": {"media_descriptions": {segment_key(image): image_description}},
    }
    timestamp = datetime.now(timezone.utc)
    sticker = {"type": "mface", "data": {"summary": "点头"}}
    face = {"type": "face", "data": {"name": "微笑"}}
    history = {"sent_at": timestamp, "user_id": "456", "segments": [sticker, face]}
    log = {"user_id": "123", "original_text": ""}

    class Database:
        write = AsyncMock()

        def check_group(self, group_id):
            return group_id

        @asynccontextmanager
        async def transaction(self, group_id):
            yield None

        async def read(self, table, *, filters, **kwargs):
            if table == "members":
                return [{"user_id": "123", "display_name": "涛涛"},
                        {"user_id": "456", "display_name": "牵鱼"}]
            if table == "log":
                return [log] if "task_id" in filters else []
            return [current] if filters == {"id": 2} else [history]

    model = SimpleNamespace(complete=AsyncMock(return_value="看见啦"))
    monkeypatch.setattr(conversation, "MODEL", model)
    ctx = SimpleNamespace(db=Database(), settings=None)
    task = {
        "group_id": "1", "task_id": "test", "request_type": "message",
        "triggered_at": timestamp, "original_text": "",
        "params": {"message_row_id": 2, "snapshot_seq": 2, "self_id": "999",
                   "segments": current["segments"], "request_text": "[图片]"},
    }

    assert await classify_task(task, ctx) == "conversation"
    assert (await conversation.run(task, ctx))["status"] == "ok"
    prompt = model.complete.call_args.kwargs["messages"][1]["content"]
    assert "牵鱼: [表情包：点头][QQ表情：微笑]" in prompt
    assert "<当前用户消息>\n发言人：涛涛\n[图片：一只蓝鲸]\n</当前用户消息>" in prompt
    assert image["data"]["url"] not in prompt
