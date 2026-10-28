'''
本文件用途：将塔罗牌图片组成消息。

配置字段：
divine_tarot_artwork_directory                 塔罗牌图片目录
divine_tarot_card_image_files                  塔罗牌名称与图片文件名的对应表
'''

from config.module_config import TarotImageConfig, load_module_config

DIVINE_TAROT_IMAGE_CONFIG = load_module_config(
    "backend/Function/divine/son_function/tarot_image_config.toml", TarotImageConfig
)

import base64
from io import BytesIO

from PIL import Image


ART = DIVINE_TAROT_IMAGE_CONFIG.divine_tarot_artwork_directory
FILES = DIVINE_TAROT_IMAGE_CONFIG.divine_tarot_card_image_files


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
