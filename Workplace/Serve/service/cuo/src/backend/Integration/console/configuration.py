'''
本文件用途：认证后的模块配置管理；敏感值只写不回显，修改后重启。

配置字段：
REGISTRY    各模块配置字段定义；所有读写限定在已注册的小配置
'''

import asyncio
import hashlib
import json
from fastapi import HTTPException, Request
from Core.configuration import REGISTRY, read, save


def install(app, require):
    lock = asyncio.Lock()

    def snapshot(name, root):
        values = read(name, root=root)
        spec = REGISTRY[name]
        version = hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return {'values': {k: v for k, v in values.items() if not spec['fields'][k]['sensitive']},
                'configured': {k: bool(v) for k, v in values.items() if spec['fields'][k]['sensitive']},
                'fields': spec['fields'], 'version': version, 'restart_required': True}

    @app.get('/console/api/configuration')
    async def catalog(request: Request):
        require(request)
        return {'modules': {name: {'source': spec['source'], 'fields': spec['fields']} for name, spec in REGISTRY.items()}}

    @app.get('/console/api/configuration/{name}')
    async def get_config(name: str, request: Request):
        ctx = require(request)
        if name not in REGISTRY: raise HTTPException(404)
        try: return snapshot(name, ctx.settings.config_root)
        except (ValueError, OSError): raise HTTPException(409, '配置尚未建立或校验失败') from None

    @app.put('/console/api/configuration/{name}')
    async def put_config(name: str, request: Request):
        ctx = require(request)
        if name not in REGISTRY: raise HTTPException(404)
        body = await request.body()
        if len(body) > 262144: raise HTTPException(413)
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict) or not isinstance(payload.get('values'), dict): raise ValueError()
        except (ValueError, TypeError): raise HTTPException(422, '配置格式错误') from None
        async with lock:
            try:
                current = snapshot(name, ctx.settings.config_root)
                if payload.get('version') != current['version']: raise HTTPException(409, '配置已修改，请刷新')
                values = read(name, root=ctx.settings.config_root)
                if set(payload['values']) - set(values): raise ValueError()
                values.update(payload['values'])
                save(name, values, root=ctx.settings.config_root)
                return snapshot(name, ctx.settings.config_root)
            except (ValueError, TypeError, OSError):
                raise HTTPException(422, '配置校验或保存失败；请检查字段、类型与范围') from None
