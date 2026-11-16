"""Read the controller's registered TOML configuration for PowerShell."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tomllib

APP_ROOT = Path(__file__).resolve().parents[3]


def validate(values):
    expected = {'ssh_host', 'connect_timeout', 'keepalive_interval',
                'keepalive_count', 'startup_timeout', 'port_attempts', 'pages'}
    if set(values) != expected:
        raise ValueError('控制台配置字段缺失或未知')
    if not isinstance(values['ssh_host'], str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', values['ssh_host']):
        raise ValueError('请填写有效的 ssh_host')
    for key in expected - {'ssh_host', 'pages'}:
        if type(values[key]) is not int or not 1 <= values[key] <= 3600:
            raise ValueError(f'{key} 必须为 1 到 3600 的整数')
    pages = values['pages']
    if not isinstance(pages, dict) or not pages:
        raise ValueError('pages 必须包含至少一个管理页面')
    for name, page in pages.items():
        if not name.strip() or not isinstance(page, dict) or set(page) != {'Local', 'Remote', 'Path'}:
            raise ValueError('页面需要 Local、Remote 和 Path')
        for key in ('Local', 'Remote'):
            if type(page[key]) is not int or not 1 <= page[key] <= 65535:
                raise ValueError('页面端口必须为 1 到 65535')
        if page['Local'] + values['port_attempts'] - 1 > 65535:
            raise ValueError('本地候选端口超出范围')
        if not isinstance(page['Path'], str) or not re.fullmatch(r'/[A-Za-z0-9/_-]*', page['Path']):
            raise ValueError('页面路径必须是有效的本地 URL 路径')
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    args = parser.parse_args()
    root = Path(os.environ.get('CUO_CONFIG_ROOT') or APP_ROOT / 'var/config')
    if not root.is_absolute():
        root = APP_ROOT / root
    path = Path(args.config) if args.config else root / 'ops/deploy/tool/control_config.toml'
    try:
        with path.open('rb') as stream:
            values = validate(tomllib.load(stream))
    except (OSError, ValueError) as error:
        parser.exit(1, f'控制台配置读取失败：{error}\n配置文件：{path}\n')
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(values, ensure_ascii=True))


if __name__ == '__main__':
    main()
