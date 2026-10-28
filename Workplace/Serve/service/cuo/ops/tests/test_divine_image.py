import base64
import asyncio
import sys
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image, ImageChops

from Function.divine.son_function.tarot_image import artwork_directory, find_card_image, message_action
from Workflow._sender_ import prepare_actions, run, _segments

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.mark.parametrize("version", ["Arknight", "TrueDark"])
@pytest.mark.parametrize("orientation", ["正位", "逆位"])
async def test_star_image_reaches_onebot(orientation, version):
    content = f"䷐ 澤雷隨\n无动爻 · 无变卦\n塔罗｜星星 · {orientation}\n\n「隨：元亨。」\n卦运 -5 · 福缘 -5"
    action = message_action(content, {"name": "星星", "orientation": orientation}, version=version)
    segments = action["segments"]
    assert segments[0]["data"]["text"].endswith(f"星星 · {orientation}\n")
    assert segments[2]["data"]["text"].startswith("\n「隨")
    assert segments[0]["data"]["text"] + segments[2]["data"]["text"] == content
    with Image.open(BytesIO(base64.b64decode(segments[1]["data"]["file"][9:]))) as actual, Image.open(find_card_image("星星", version)) as source:
        expected = source.transpose(Image.Transpose.ROTATE_180) if orientation == "逆位" else source
        assert actual.size == expected.size
        assert ImageChops.difference(actual.convert("RGB"), expected.convert("RGB")).getbbox() is None
    calls = []
    async def call(api, params, **kwargs):
        calls.append((api, params))
        return {"status": "ok", "retcode": 0, "data": {"message_id": 1}}
    ctx = SimpleNamespace(settings=SimpleNamespace(groups={"123": {}}, data_root=artwork_directory(version), max_message_length=1500), onebot=SimpleNamespace(call=call))
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


@pytest.mark.parametrize("name", ["愚者","魔术师","女祭司","皇后","皇帝","教宗","恋人","战车","力量","隐者","命运之轮","正义","倒吊人","死神","节制","恶魔","高塔","星星","月亮","太阳","审判","世界"])
def test_complete_truedark_deck(name):
    path = find_card_image(name, "TrueDark")
    assert path is not None and path.parent.name == "Tarot -version-TrueDark"
    assert path.suffix == ".jpg"


def test_missing_card_and_ignored_supplements():
    assert find_card_image("太阳", "Arknight") is None
    assert find_card_image("无尽", "TrueDark") is None
    assert find_card_image("圣杯首牌", "TrueDark") is None
    content = "塔罗｜太阳 · 正位\n正文"
    assert "segments" not in message_action(content, {"name":"太阳","orientation":"正位"}, version="Arknight")


@pytest.mark.parametrize("version", ["../TrueDark", "", "MissingDeck"])
def test_invalid_deck(version):
    with pytest.raises(ValueError):
        artwork_directory(version)


def test_duplicate_card_is_not_silently_chosen(tmp_path, monkeypatch):
    from Function.divine.son_function import tarot_image
    deck = tmp_path / "Tarot -version-Test"
    deck.mkdir()
    (deck / "XVII 星 The Star.jpg").write_bytes(b"first")
    (deck / "XVII 星星 The Star.png").write_bytes(b"second")
    config = tarot_image.DIVINE_TAROT_IMAGE_CONFIG.model_copy(update={"divine_tarot_picture_directory": tmp_path, "divine_tarot_version": "Test"})
    monkeypatch.setattr(tarot_image, "DIVINE_TAROT_IMAGE_CONFIG", config)
    with pytest.raises(ValueError, match="duplicate_tarot_image"):
        find_card_image("星星")
