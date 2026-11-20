from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from Function.divine.divine import candidates_from
from Function.summary.son_function.image_processor import segment_key
from Function.summary.son_function.normalize_messages import normalize_messages


def message(message_id, *segments, text="", user_id="101"):
    return {
        "message_id": message_id,
        "user_id": user_id,
        "sent_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "segments": list(segments),
        "text": text,
    }


def segment(kind, **data):
    return {"type": kind, "data": data}


async def normalize(rows):
    db = SimpleNamespace(check_group=str, read=AsyncMock(return_value=[]))
    return await normalize_messages(rows, SimpleNamespace(db=db), "100")


async def test_attachment_labels_and_descriptions_never_become_candidates():
    image = segment("image", file="test.png")
    rows = [
        message("1", image),
        message("2", segment("mface", summary="怪物猎人")),
        message("3", segment("face", name="排位连跪")),
        message("4", segment("at", qq="101")),
        message("5", text="图片 表情包"),
    ]
    rows[0]["processing"] = {
        "media_descriptions": {
            segment_key(image): {"status": "ready", "display_description": "火锅"}
        }
    }
    records, refs = await normalize(rows)
    assert any("[图片：火锅]" in record["text"] for record in records)
    assert candidates_from(records, refs, "101", source_rows=rows) == []


async def test_mixed_and_legacy_messages_keep_only_written_evidence():
    rows = [
        message("1", text="昨晚 [图片：怪物猎人[火锅]] [CQ:face,id=123] 降温了"),
        message(
            "2",
            segment("reply", id="1"),
            segment("image", summary="投资"),
            segment("text", text="周末吃火锅"),
            segment("mface", summary="怪物猎人"),
            text="[图片]周末吃火锅[表情包]",
            user_id="202",
        ),
        message("3", segment("text", text="晚饭"), user_id="202"),
    ]
    rows[2]["processing"] = {"receiver": {"at_bot": True}}
    records, refs = await normalize(rows)

    candidates = {
        item["keyword"]: item for item in candidates_from(records, refs, "101", source_rows=rows)
    }

    assert set(candidates) == {"降温", "周末", "火锅"}
    legacy_excerpt, = candidates["降温"]["source_excerpt"]
    assert legacy_excerpt["ref"] == "m00001"
    assert legacy_excerpt["text"].split() == ["昨晚", "降温了"]
    assert candidates["火锅"]["speaker_relation"] == "reply"
    assert candidates["火锅"]["source_excerpt"] == [
        {"ref": "m00002", "text": "周末吃火锅"}
    ]
