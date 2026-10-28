'''
本文件用途：生成六爻并匹配本卦和变卦。

配置字段：
divine_zhou_yi_hexagrams_file                  六十四卦资料文件
'''

from config.module_config import ZhouYiConfig, load_module_config

DIVINE_ZHOU_YI_CONFIG = load_module_config(
    "backend/Function/divine/son_function/zhou_yi_config.toml", ZhouYiConfig
)

import json
import secrets
from typing import Any, Dict, List, Optional


def load_hexagrams(path: Optional[str] = None) -> List[Dict[str, Any]]:
    if path is None:
        path = DIVINE_ZHOU_YI_CONFIG.divine_zhou_yi_hexagrams_file
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list) or len(data) != 64:
        raise ValueError('Expected 64 hexagrams')
    numbers = set()
    bits_set = set()
    for h in data:
        if not isinstance(h, dict):
            raise ValueError('Hexagram entry must be dict')
        n = h.get('number')
        if not isinstance(n, int) or n < 1 or n > 64:
            raise ValueError('Invalid hexagram number')
        if n in numbers:
            raise ValueError('Duplicate hexagram number')
        numbers.add(n)
        bits = h.get('bits_bottom_up')
        if not isinstance(bits, str) or len(bits) != 6 or any(b not in '01' for b in bits):
            raise ValueError('Invalid bits_bottom_up')
        bits_set.add(bits)
        lines = h.get('lines')
        if not isinstance(lines, list) or len(lines) != 6 or any(not isinstance(l, str) or not l.strip() for l in lines):
            raise ValueError('Invalid lines')
        expected_symbol = chr(0x4DC0 + n - 1)
        if h.get('symbol') != expected_symbol:
            raise ValueError('Symbol mismatch for hexagram %d' % n)
    if len(bits_set) != 64:
        raise ValueError('Bits must contain all 64 combinations')
    qian = next((h for h in data if h['number'] == 1), None)
    kun = next((h for h in data if h['number'] == 2), None)
    if not qian.get('special_text'):
        raise ValueError('Qian special_text missing')
    if not kun.get('special_text'):
        raise ValueError('Kun special_text missing')
    return data


def from_lines(line_values: List[int], hexagrams: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if not isinstance(line_values, list) or len(line_values) != 6:
        raise ValueError('line_values must be list of 6')
    for v in line_values:
        if isinstance(v, bool) or not isinstance(v, int) or v not in (6, 7, 8, 9):
            raise ValueError('line value must be 6,7,8,9')
    if hexagrams is None:
        hexagrams = load_hexagrams()
    lookup = {h['bits_bottom_up']: h for h in hexagrams}
    base_bits = ''.join(str(v % 2) for v in line_values)
    changed_bits = ''.join(str(1 - (v % 2)) if v in (6, 9) else str(v % 2) for v in line_values)
    moving_lines = [i + 1 for i, v in enumerate(line_values) if v in (6, 9)]
    base = lookup.get(base_bits)
    changed = lookup.get(changed_bits)
    if base is None or changed is None:
        raise ValueError('Hexagram lookup failed')
    return {
        'line_values': list(line_values),
        'base_bits': base_bits,
        'changed_bits': changed_bits,
        'moving_lines': moving_lines,
        'has_change': len(moving_lines) > 0,
        'base': base,
        'changed': changed,
    }


def cast(rng: Optional[Any] = None) -> Dict[str, Any]:
    if rng is None:
        rng = secrets.SystemRandom()
    line_values = []
    for _ in range(6):
        total = sum(rng.choice([2, 3]) for _ in range(3))
        line_values.append(total)
    return from_lines(line_values)
