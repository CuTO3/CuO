'''
本文件用途：读取并选择固定解卦资料。

配置字段：
divine_fixed_readings_file                     固定解卦资料文件
'''

from Core.module_config import ReadingsConfig, load_module_config

DIVINE_READINGS_CONFIG = load_module_config(
    "backend/Function/divine/son_function/readings_config.toml", ReadingsConfig
)

import copy
import json
from functools import lru_cache

VERSION = "readings-v1"


def reading_key(zhou):
    moving = sorted(zhou["moving_lines"])
    return f'{zhou["base"]["number"]}:' + (",".join(map(str, moving)) or "0")


@lru_cache(maxsize=1)
def load_readings():
    document = json.loads(DIVINE_READINGS_CONFIG.divine_fixed_readings_file.read_text(encoding="utf-8"))
    if document["version"] != VERSION or len(document["readings"]) != 4096:
        raise ValueError("invalid fixed readings catalog")
    return document["readings"]


def select_reading(zhou):
    row = copy.deepcopy(load_readings()[reading_key(zhou)])
    if row["changed_number"] != zhou["changed"]["number"]:
        raise ValueError("reading changed hexagram mismatch")
    return row
