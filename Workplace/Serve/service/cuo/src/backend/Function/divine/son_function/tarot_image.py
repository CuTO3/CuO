'''
本文件用途：按牌组目录后缀与标准塔罗牌名称选择图片，将图片组成消息。

配置字段：
divine_tarot_picture_directory                 塔罗牌图片根目录
divine_tarot_version                           牌组目录后缀，如 Arknight、TrueDark
'''

# 路径规则：图片根目录 / Tarot -version-{牌组目录后缀}
# 文件规则：编号 中文牌名 英文牌名.ext，按中文牌名匹配，支持 PNG、JPG、JPEG、WebP。

import base64
from io import BytesIO
import re

from Core.module_config import TarotImageConfig, load_module_config

DIVINE_TAROT_IMAGE_CONFIG = load_module_config(
    "src/backend/Function/divine/son_function/tarot_image_config.toml", TarotImageConfig
)

from PIL import Image


# 别名只处理牌名差异；不绑定图片文件名、编号和扩展名。
ALIASES = {"星星": "星", "教皇": "教宗", "女皇": "皇后", "塔": "高塔"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def artwork_directory(version=None):
    config = DIVINE_TAROT_IMAGE_CONFIG
    version = config.divine_tarot_version if version is None else version
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", version):
        raise ValueError("invalid_tarot_version")
    root = config.divine_tarot_picture_directory.resolve()
    directory = root / ("Tarot -version-" + version)
    if not directory.is_dir() or directory.is_symlink() or not directory.resolve().is_relative_to(root):
        raise ValueError("invalid_tarot_directory")
    return directory


def find_card_image(name, version=None):
    """标准文件名：罗马数字 中文牌名 英文牌名.ext，只扫描根目录。"""
    name = ALIASES.get(name, name)
    matches = []
    for path in sorted(artwork_directory(version).iterdir()):
        if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file() or path.is_symlink():
            continue
        parts = path.stem.split(maxsplit=2)
        if len(parts) != 3 or not re.fullmatch(r"0|[IVXLCDM]+", parts[0]):
            continue
        if ALIASES.get(parts[1], parts[1]) == name:
            matches.append(path)
    if len(matches) > 1:
        raise ValueError(f"duplicate_tarot_image: {name}")
    return matches[0] if matches else None


def message_action(content, tarot, *, version=None):
    action = {"type": "send_message", "text": content}
    heading = f'塔罗｜{tarot["name"]} · {tarot["orientation"]}\n'
    before, separator, after = content.partition(heading)
    if not separator:
        return action
    path = find_card_image(tarot["name"], version)
    if path is None:
        return action
    with Image.open(path) as source:
        picture = source.transpose(Image.Transpose.ROTATE_180) if tarot["orientation"] == "逆位" else source
        buffer = BytesIO()
        picture.save(buffer, format="PNG")
    action["segments"] = [
        {"type": "text", "data": {"text": before + separator}},
        {"type": "image", "data": {"file": "base64://" + base64.b64encode(buffer.getvalue()).decode("ascii")}},
        {"type": "text", "data": {"text": after}},
    ]
    return action
