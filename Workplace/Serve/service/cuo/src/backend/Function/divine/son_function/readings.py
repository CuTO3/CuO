"""Fixed, versioned readings. Runtime never asks a model to interpret a hexagram."""
import copy
import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
VERSION = "readings-v1"


def reading_key(zhou):
    moving = sorted(zhou["moving_lines"])
    return f'{zhou["base"]["number"]}:' + (",".join(map(str, moving)) or "0")


@lru_cache(maxsize=1)
def load_readings():
    document = json.loads((DATA / "readings.json").read_text(encoding="utf-8"))
    if document["version"] != VERSION or len(document["readings"]) != 4096:
        raise ValueError("invalid fixed readings catalog")
    return document["readings"]


def select_reading(zhou):
    row = copy.deepcopy(load_readings()[reading_key(zhou)])
    if row["changed_number"] != zhou["changed"]["number"]:
        raise ValueError("reading changed hexagram mismatch")
    return row
