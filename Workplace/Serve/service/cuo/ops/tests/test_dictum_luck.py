import itertools

import pytest

from Function.divine.divine import draw_dictum_luck
from Function.divine.son_function.dictum import select_dictum
from Function.divine.son_function.luck import assess_dictum
from Function.divine.son_function.tarot import map_tarot
from Function.divine.son_function.zhou_yi import from_lines, load_hexagrams


def quote(text):
    return {"primary": {"text_display": text}, "auxiliary": []}


@pytest.mark.parametrize("text,direction", [
    ("随：元亨。利贞。无咎。", 1),
    ("乾：元亨。利贞。", 1),
    ("贞吉，悔亡。", 1),
    ("无不利。", 1),
    ("征凶，无攸利。", -1),
    ("不利有攸往。", -1),
    ("亢龙，有悔。", -1),
    ("贞厉。", -1),
    ("贞厲。", -1),
    ("无咎。", 0),
    ("无悔，无吝。", 0),
    ("悔亡。", 1),
    ("先吉后凶。", -1),
    ("厉，终吉。", 1),
    ("潜龙勿用。", 0),
])
def test_dictum_direction_and_random_extremes(text, direction):
    dictum = quote(text)
    assert assess_dictum(dictum)["direction"] == direction
    for u in (0, 0.25, 0.5, 0.75, 0.99999999999):
        delta = draw_dictum_luck(dictum, type("R", (), {"random": lambda self: u})())
        assessment = assess_dictum(dictum)
        assert assessment["magnitude_min"] <= abs(delta) <= assessment["magnitude_max"]
        assert (delta > 0) - (delta < 0) == direction


def test_only_displayed_primary_decides_direction():
    dictum = quote("吉。")
    dictum["auxiliary"] = [{"text_display": "凶。"}]
    assert assess_dictum(dictum)["direction"] == 1


def test_all_casts_match_primary_and_tarot():
    table = load_hexagrams()
    rng = type("R", (), {"random": lambda self: 0})()
    for values in itertools.product((6, 7, 8, 9), repeat=6):
        zhou = from_lines(list(values), table)
        dictum = select_dictum(zhou)
        delta = draw_dictum_luck(dictum, rng)
        assert (delta > 0) - (delta < 0) == assess_dictum(dictum)["direction"]
        assert map_tarot(zhou, delta)["orientation"] == ("逆位" if delta < 0 else "正位")


@pytest.mark.parametrize("text,direction,level", [
    ("无咎。", 0, "平"),
    ("贞丈人吉，无咎。", 1, "吉"),
    ("大吉，无咎。", 1, "大吉"),
    ("君子终日乾乾，夕惕若；厉，无咎。", -1, "小凶"),
    ("过涉灭顶，凶，无咎。", -1, "凶"),
    ("干父之蛊，有子考，无咎，厉终吉。", 1, "转吉"),
    ("小人无咎，君子吝。", -1, "小凶"),
    ("损其疾，使遄有喜，无咎。", 1, "小吉"),
    ("噬肉，遇毒；小吝，无咎。", -1, "小凶"),
    ("无平不陂，无往不复，艰贞无咎。勿恤其孚，于食有福。", 1, "小吉"),
    ("益之用凶事，无咎。有孚中行，告公用圭。", 1, "小吉"),
    ("噬乾肉，得黄金，贞厉，无咎。", 0, "平"),
    ("吉。后夫凶。", 0, "吉凶参半"),
])
def test_no_blame_context(text, direction, level):
    assessment = assess_dictum(quote(text))
    assert assessment["direction"] == direction
    assert assessment["level"] == level
