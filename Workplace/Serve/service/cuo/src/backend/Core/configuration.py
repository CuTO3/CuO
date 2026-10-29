'''
本文件用途：后端小配置的字段注册、读取、校验和安全保存。

配置字段：
CUO_CONFIG_ROOT    私有小配置根目录；默认使用应用 var/config
'''

import json
import math
import os
import tempfile
import tomllib
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

APP_ROOT = Path(__file__).resolve().parents[3]

REGISTRY = {}


def config_root():
    root = Path(os.environ.get('CUO_CONFIG_ROOT') or APP_ROOT / 'var/config')
    return root if root.is_absolute() else APP_ROOT / root


def validate(spec, values):
    if set(values) != set(spec['fields']):
        raise ValueError('配置字段缺失或包含未知字段')
    for name, field in spec['fields'].items():
        value = values[name]
        kind = field['type']
        valid = (type(value) is bool if kind == 'bool' else
                 type(value) is int if kind == 'int' else
                 type(value) in (int, float) if kind == 'float' else
                 isinstance(value, list) and all(isinstance(x, str) for x in value) if kind == 'strings' else
                 isinstance(value, dict) if kind == 'table' else isinstance(value, str))
        if not valid or ('min' in field and value < field['min']) or ('max' in field and value > field['max']):
            raise ValueError(f'配置字段格式或范围错误：{name}')
        if kind == 'float' and not math.isfinite(value):
            raise ValueError(f'配置数字必须有限：{name}')
    if 'postgresql_pool_min_connections' in values and values['postgresql_pool_min_connections'] > values['postgresql_pool_max_connections']:
        raise ValueError('数据库连接池上下限错误')
    if 'task_queue_retry_delays_seconds' in values and any(not item.isdecimal() or int(item) <= 0 for item in values['task_queue_retry_delays_seconds']):
        raise ValueError('重试延迟必须为正整数秒')
    if 'memento_workbook_filename' in values:
        name = values['memento_workbook_filename']
        if not name or any(char in name for char in '/\\:') or not name.endswith('.xlsx'):
            raise ValueError('工作簿必须是 xlsx 文件名')
    if 'postgresql_registered_groups' in values:
        schemas = []
        for group, item in values['postgresql_registered_groups'].items():
            if not isinstance(group, str) or not group.isascii() or not group.isdecimal() or not isinstance(item, dict):
                raise ValueError('群配置格式错误')
            if set(item) - {'schema', 'enabled'} or type(item.get('enabled', True)) is not bool:
                raise ValueError('群配置字段错误')
            schema = item.get('schema', group)
            if not isinstance(schema, str) or not schema.isascii() or not schema.isdecimal():
                raise ValueError('群 schema 格式错误')
            if item.get('enabled', True): schemas.append(schema)
        if len(set(schemas)) != len(schemas): raise ValueError('群 schema 不可重复')
    if spec.get('model_class'):
        from Core import module_config
        from pydantic import ValidationError
        try:
            config = getattr(module_config, spec['model_class']).model_validate(values)
            module_config.validate_config(config, spec['path'])
        except ValidationError: raise ValueError('模块配置字段格式或范围错误') from None
    prefix = spec.get('ai_prefix')
    if prefix and values[prefix + '_enabled']:
        try:
            url = urlsplit(values[prefix + '_base_url'])
            valid = url.scheme in ('https', 'http') and bool(url.hostname) and not (url.username or url.password or url.query or url.fragment)
        except ValueError:
            valid = False
        if not valid or not values[prefix + '_api_key'].strip() or not values[prefix + '_model_name'].strip():
            raise ValueError('启用 AI 前必须填写有效 LiteLLM 地址、专用 Key 和模型名称')
    return values


def read(name, *, root=None):
    spec = REGISTRY[name]
    path = Path(root or config_root()) / spec['path']
    try:
        with path.open('rb') as stream:
            values = tomllib.load(stream)
    except (ValueError, OSError):
        raise ValueError(f'无法读取配置：{spec["path"]}') from None
    return validate(spec, values)


def load(name):
    return MappingProxyType(read(name))


def resource(value):
    path = Path(value)
    return path if path.is_absolute() else APP_ROOT / path


def toml_text(values):
    def scalar(value):
        if isinstance(value, bool): return 'true' if value else 'false'
        return json.dumps(value, ensure_ascii=False)
    lines = []
    for name, value in values.items():
        if not isinstance(value, dict): lines.append(f'{name} = {scalar(value)}')
    def table(name, value):
        lines.append('\n[' + '.'.join(json.dumps(x) for x in name) + ']')
        for key, item in value.items():
            if not isinstance(item, dict): lines.append(f'{json.dumps(key)} = {scalar(item)}')
        for key, item in value.items():
            if isinstance(item, dict): table(name + [key], item)
    for name, value in values.items():
        if isinstance(value, dict): table([name], value)
    return '\n'.join(lines) + '\n'


def save(name, values, *, root=None):
    spec = REGISTRY[name]
    validate(spec, values)
    path = Path(root or config_root()) / spec['path']
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(toml_text(values))
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _read_registry():
    document = json.loads((config_root() / 'config_index.json').read_text(encoding='utf-8'))
    result = {}
    for entry in document['modules']:
        if not entry.get('config'): continue
        name = entry['module_id']
        path = Path(entry['config'])
        if path.is_absolute() or '..' in path.parts or path.suffix != '.toml':
            raise ValueError('invalid config index path')
        result[name] = {'source': entry['source'], 'path': entry['config'], 'fields': entry['field_metadata']}
        for key in ('ai_prefix', 'model_class'):
            if key in entry: result[name][key] = entry[key]
    return result

REGISTRY.update(_read_registry())
