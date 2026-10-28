import itertools
from types import SimpleNamespace

from Function.divine.son_function.readings import select_reading, load_readings
from Function.divine.son_function.zhou_yi import from_lines, load_hexagrams
from Function.divine.son_function.dictum import select_dictum
from Function.divine.son_function.merge_message import render
from Function.divine.son_function.AI_divine import generate
from Function.divine.divine import draw_dictum_luck


def test_all_fixed_cases_match_cast_and_primary():
    table = load_hexagrams()
    keys = set()
    for values in itertools.product((6, 7, 8, 9), repeat=6):
        z = from_lines(list(values), table)
        r = select_reading(z)
        keys.add(r['key'])
        q = select_dictum(z)
        assert r['primary'] == q['primary']
        assert r['moving_lines'] == z['moving_lines']
        assert r['changed_number'] == z['changed']['number']
        for field in ('interpretation', 'title', 'theme', 'closing'):
            assert r[field].strip()
        q['reading_fortune'] = r['fortune']
        for u in (0, .5, .99999999999):
            delta = draw_dictum_luck(q, type('R', (), {'random': lambda self: u})())
            assert r['fortune']['magnitude_min'] <= abs(delta) <= r['fortune']['magnitude_max']
            assert (delta > 0) - (delta < 0) == r['fortune']['direction']
    assert len(keys) == len(load_readings()) == 4096


async def test_reading_render_and_no_evidence_fallback():
    z = from_lines([7,7,9,8,8,8])
    z['reading'] = select_reading(z)
    r = z['reading']
    assert r['changed_number'] == 19
    assert r['fortune']['direction'] == 1
    ai = await generate(z, {}, select_dictum(z), [], 2, SimpleNamespace())
    assert ai['refs'] == [] and ai['keyword'] == '今日一应'
    text = render(z, {'name':'星星','orientation':'正位'}, ai, 2, 20)
    assert text.startswith('䷊ 地天泰 → ䷒ 地泽临 | 顺中有变，临事有度')
    assert '\n解卦\n' in text and '\n应事 · 今日一应\n' in text
    assert text.endswith(r['closing'])
    r['title'] = 'modified'
    assert select_reading(z)['title'] != 'modified'


async def test_unsnapshotted_draft_uses_fixed_fallback():
    from Function.divine.son_function.AI_divine import fallback
    z = from_lines([7,7,9,8,8,8])
    expected = select_reading(z)
    ai = await generate(z, {}, select_dictum(z), [], -2, SimpleNamespace())
    assert ai == fallback(z)
    assert ai['advice'] == expected['fallback_advice']
    assert ai['refs'] == []
