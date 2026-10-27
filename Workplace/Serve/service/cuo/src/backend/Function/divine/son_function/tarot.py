from typing import Any, Dict


_TRIGRAM_TAROT = {
    '乾': ['皇帝', '战车', '太阳'],
    '坤': ['皇后', '世界', '节制'],
    '震': ['高塔', '愚者', '战车'],
    '巽': ['魔术师', '恋人', '星星'],
    '坎': ['月亮', '隐者', '倒吊人'],
    '離': ['太阳', '正义', '审判'],
    '离': ['太阳', '正义', '审判'],
    '艮': ['隐者', '力量', '节制'],
    '兌': ['星星', '命运之轮', '皇后'],
    '兑': ['星星', '命运之轮', '皇后'],
}

_CARD_IDS = {
    '皇帝': '04', '战车': '07', '太阳': '19', '皇后': '03', '世界': '21', '节制': '14',
    '高塔': '16', '愚者': '00', '魔术师': '01', '恋人': '06', '星星': '17',
    '月亮': '18', '隐者': '09', '倒吊人': '12', '正义': '11', '审判': '20',
    '力量': '08', '命运之轮': '10',
}


def map_tarot(zhou_result: Dict[str, Any], luck_delta: int) -> Dict[str, Any]:
    if isinstance(luck_delta, bool) or not isinstance(luck_delta, int):
        raise ValueError('luck_delta must be int')
    if luck_delta < -10 or luck_delta > 10:
        raise ValueError('luck_delta must be between -10 and 10')
    if not isinstance(zhou_result, dict):
        raise ValueError('zhou_result must be dict')
    hexagram = zhou_result['changed'] if zhou_result.get('has_change') else zhou_result['base']
    upper = hexagram.get('upper_trigram', '')
    cards = _TRIGRAM_TAROT.get(upper)
    if cards is None:
        raise ValueError('Unknown upper trigram: %s' % upper)
    moving = zhou_result.get('moving_lines', [])
    idx = len(moving) % 3
    name = cards[idx]
    card_id = _CARD_IDS[name]
    orientation = '正位' if luck_delta >= 0 else '逆位'
    return {
        'card_id': card_id,
        'name': name,
        'orientation': orientation,
        'mapping_version': 'v1',
    }
