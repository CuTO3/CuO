from typing import Any, Dict, List
from .zhou_yi import load_hexagrams


def _make_quote(hexagram: Dict[str, Any], position: int, source_label: str) -> Dict[str, Any]:
    if position is None or position == 0:
        text = hexagram.get('judgment')
        pos = None
    elif 1 <= position <= 6:
        lines = hexagram.get('lines', [])
        text = lines[position - 1]
        pos = position
    else:
        raise ValueError('Invalid position')
    if not text or not str(text).strip():
        raise ValueError('Missing text')
    return {
        'text_original': text,
        'text_display': text,
        'hexagram_number': hexagram['number'],
        'line_position': pos,
        'source_label': source_label,
        'source_url': hexagram.get('source_url', ''),
    }


def _get_special(hexagram: Dict[str, Any]) -> str:
    text = hexagram.get('special_text')
    if not text:
        raise ValueError('special_text missing')
    return text


def select_dictum(zhou_result: Dict[str, Any]) -> Dict[str, Any]:
    base = zhou_result.get('base')
    changed = zhou_result.get('changed')
    moving = zhou_result.get('moving_lines', [])
    n = len(moving)
    primary = None
    auxiliary: List[Dict[str, Any]] = []

    if n == 0:
        primary = _make_quote(base, 0, '本卦卦辞')
    elif n == 1:
        primary = _make_quote(base, moving[0], '本卦动爻')
    elif n == 2:
        m1, m2 = sorted(moving)
        primary = _make_quote(base, m2, '本卦动爻')
        auxiliary.append(_make_quote(base, m1, '本卦动爻'))
    elif n == 3:
        primary = _make_quote(base, 0, '本卦卦辞')
        auxiliary.append(_make_quote(changed, 0, '变卦卦辞'))
    elif n == 4:
        unmoved = [i + 1 for i in range(6) if (i + 1) not in moving]
        low, high = sorted(unmoved)
        primary = _make_quote(changed, low, '变卦未动爻')
        auxiliary.append(_make_quote(changed, high, '变卦未动爻'))
    elif n == 5:
        unmoved = [i + 1 for i in range(6) if (i + 1) not in moving]
        primary = _make_quote(changed, unmoved[0], '变卦未动爻')
    elif n == 6:
        special = _get_special(base) if base.get('number') in (1, 2) else None
        if special:
            auxiliary.append(_make_quote(changed, 0, '变卦卦辞'))
            special_num = base['number']
            primary = {
                'text_original': special,
                'text_display': special,
                'hexagram_number': special_num,
                'line_position': 7,
                'source_label': '用九' if special_num == 1 else '用六',
                'source_url': base.get('source_url', ''),
            }
        else:
            primary = _make_quote(changed, 0, '变卦卦辞')
    else:
        raise ValueError('Invalid moving lines count')

    return {
        'primary': primary,
        'auxiliary': auxiliary,
        'rule_version': 'v1',
    }
