'''
本文件用途：从 var/config 的同目录 example 建立部署配置，只补缺失文件。

配置字段：
CUO_CONFIG_ROOT    配置目标根目录；命令行 --destination 可覆盖
'''

import argparse
import json
import os
from pathlib import Path
import tomllib

APP_ROOT = Path(__file__).resolve().parents[1]


def initialize(destination, source=None):
    source = Path(source or APP_ROOT / 'var/config').resolve()
    destination = Path(destination).resolve()
    index = source / 'config_index.json'
    document = json.loads(index.read_text(encoding='utf-8'))
    planned = []
    for entry in document['modules']:
        if not entry.get('config'): continue
        relative = Path(entry['config'])
        if relative.is_absolute() or '..' in relative.parts or relative.suffix != '.toml':
            raise ValueError('invalid configuration index path')
        example = source / relative.with_name(relative.stem + '.example.toml')
        content = example.read_bytes()
        tomllib.loads(content.decode('utf-8'))
        planned.append((destination / relative, content))
    planned.append((destination / 'config_index.json', index.read_bytes()))
    created = 0
    for target, content in planned:
        if not target.resolve().is_relative_to(destination):
            raise ValueError('configuration target escapes destination')
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open('xb') as stream: stream.write(content)
        except FileExistsError:
            continue
        os.chmod(target, 0o600)
        created += 1
    return created


def main():
    parser = argparse.ArgumentParser(description='从 example 补齐私有配置，不覆盖已有配置。')
    parser.add_argument('--destination', default=os.environ.get('CUO_CONFIG_ROOT') or str(APP_ROOT / 'var/config'))
    arguments = parser.parse_args()
    print(f'已建立 {initialize(arguments.destination)} 个缺失配置文件；请填写必要私有参数后启动。')


if __name__ == '__main__': main()
