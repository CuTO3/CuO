import base64
import asyncio
import sys
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image, ImageChops

from Function.divine.son_function.tarot_image import ART, FILES, message_action
from Workflow._sender_ import prepare_actions, run, _segments

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.mark.parametrize("orientation", ["正位", "逆位"])
async def test_star_image_reaches_onebot(orientation):
    content = f"䷐ 澤雷隨\n无动爻 · 无变卦\n塔罗｜星星 · {orientation}\n\n「隨：元亨。」\n卦运 -5 · 福缘 -5"
    action = message_action(content, {"name": "星星", "orientation": orientation})
    segments = action["segments"]
    assert segments[0]["data"]["text"].endswith(f"星星 · {orientation}\n")
    assert segments[2]["data"]["text"].startswith("\n「隨")
    assert segments[0]["data"]["text"] + segments[2]["data"]["text"] == content
    with Image.open(BytesIO(base64.b64decode(segments[1]["data"]["file"][9:]))) as actual, Image.open(ART / FILES["星星"]) as source:
        expected = source.transpose(Image.Transpose.ROTATE_180) if orientation == "逆位" else source
        assert actual.size == expected.size
        assert ImageChops.difference(actual.convert("RGB"), expected.convert("RGB")).getbbox() is None
    calls = []
    async def call(api, params, **kwargs):
        calls.append((api, params))
        return {"status": "ok", "retcode": 0, "data": {"message_id": 1}}
    ctx = SimpleNamespace(settings=SimpleNamespace(groups={"123": {}}, data_root=ART, max_message_length=1500), onebot=SimpleNamespace(call=call))
    task_id = str(uuid4())
    prepared = await prepare_actions("123", task_id, [action], context=ctx)
    assert len(prepared) == 1
    prepared[0]["status"] = "sending"
    assert (await run("123", task_id, prepared[0], context=ctx))["status"] == "sent"
    assert calls == [("send_group_msg", {"group_id": 123, "message": segments})]


def test_missing_art_keeps_text():
    assert message_action("text", {"name": "太阳", "orientation": "正位"}) == {"type": "send_message", "text": "text"}


@pytest.mark.parametrize("file", ["file:///etc/passwd", "https://example.com/image.png", "base64://broken"])
def test_segment_image_rejects_external_paths(file):
    with pytest.raises(ValueError, match="invalid_segments"):
        _segments([{"type": "image", "data": {"file": file}}])
