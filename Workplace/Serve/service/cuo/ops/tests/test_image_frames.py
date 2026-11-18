import base64
import io

from PIL import Image

from Function.summary.son_function import image_processor
from Integration.console.media import record
from datetime import datetime, timezone


def decode(encoded):
    return Image.open(io.BytesIO(base64.b64decode(encoded.split(",", 1)[1])))


def test_long_screenshot_sends_overview_and_readable_crops(tmp_path, monkeypatch):
    monkeypatch.setattr(image_processor, "CONFIG", {
        **image_processor.CONFIG, "summary_image_thumbnail_side_pixels": 120,
    })
    path = tmp_path / "screenshot.png"
    image = Image.new("RGB", (60, 300))
    for y, color in enumerate(("red", "green", "blue")):
        image.paste(color, (0, y * 100, 60, (y + 1) * 100))
    image.save(path)

    overview, top, middle, bottom = map(decode, image_processor.frames(path))
    assert overview.size == (24, 120)
    assert [frame.size for frame in (top, middle, bottom)] == [(60, 120)] * 3
    assert top.getpixel((30, 60))[0] > 200
    assert middle.getpixel((30, 60))[1] > 100
    assert bottom.getpixel((30, 60))[2] > 200


def test_animation_samples_intermediate_actions_and_last_frame(tmp_path):
    path = tmp_path / "sticker.gif"
    colors = [20, 40, 60, 80, 100, 120, 140, 160, 180]
    originals = [Image.new("RGB", (16, 16), (value,) * 3) for value in colors]
    originals[0].save(path, save_all=True, append_images=originals[1:], duration=60)

    sampled = [decode(frame).getpixel((8, 8))[0] for frame in image_processor.frames(path)]
    assert sampled == colors[::2]


def test_list_display_is_short_and_full_description_remains_available():
    line = "一二三四五六七八九十一二三四五六七"
    full = "角色举着黄色长棍。字幕：我正等着你陪我玩几把呢"
    label, description = image_processor.split_description(f"显示：{line}\n{full}")
    assert label == line[:15]
    assert description == full

    segment = {"type": "image", "data": {}}
    item = {"status": "ready", "display_description": line, "description": full}
    row = {"id": 1, "sent_at": datetime.now(timezone.utc),
           "processing": {"media_descriptions": {image_processor.segment_key(segment): item}}}
    result = record(row, segment, 1)
    assert result["display_description"] == label
    assert result["description"] == full
    item["manually_reviewed"] = True
    assert record(row, segment, 1)["display_description"] == full[:15]
