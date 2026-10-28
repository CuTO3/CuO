"""Build a chat message from the supplied tarot artwork."""
import base64
from io import BytesIO
from pathlib import Path

from PIL import Image


ART = Path(__file__).resolve().parents[1] / "data" / "Tarot -version-Arknight"
# Match names, since this deck numbers Strength differently from our mapping.
FILES = {
    "魔术师": "I 魔术师 The Magician.png",
    "隐者": "IX 隐者 The Hermit.png",
    "教宗": "V 教宗 The Pope.png",
    "战车": "VII 战车 The Chariot.png",
    "力量": "XI 力量 The Strength.png",
    "倒吊人": "XII 倒吊人 The Hanged One.png",
    "节制": "XIV 节制 Temperance.png",
    "星星": "XVII 星 The Star.png",
}


def message_action(content, tarot):
    action = {"type": "send_message", "text": content}
    filename = FILES.get(tarot["name"])
    if filename is None or not (ART / filename).is_file():
        return action
    heading = f'塔罗｜{tarot["name"]} · {tarot["orientation"]}\n'
    before, separator, after = content.partition(heading)
    if not separator:
        return action
    with Image.open(ART / filename) as source:
        picture = source.transpose(Image.Transpose.ROTATE_180) if tarot["orientation"] == "逆位" else source
        buffer = BytesIO()
        picture.save(buffer, format="PNG")
    action["segments"] = [
        {"type": "text", "data": {"text": before + separator}},
        {"type": "image", "data": {"file": "base64://" + base64.b64encode(buffer.getvalue()).decode("ascii")}},
        {"type": "text", "data": {"text": after}},
    ]
    return action
