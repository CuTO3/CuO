"""Authenticated restart of the fixed CuO systemd service."""
import asyncio
import os

from fastapi import HTTPException, Request


async def restart_service():
    process = await asyncio.create_subprocess_exec(
        '/usr/bin/systemctl', '--no-ask-password', '--no-block',
        'restart', 'cuo-backend.service',
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=10)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError('重启请求超时，请检查服务状态') from None
    if process.returncode:
        raise RuntimeError('重启请求被拒绝，请检查 CuO 的 systemd 重启权限')


def install(app, require):
    lock = asyncio.Lock()
    pending = False

    @app.post('/console/api/service/restart', status_code=202)
    async def restart(request: Request):
        nonlocal pending
        require(request)
        if not os.environ.get('INVOCATION_ID'):
            raise HTTPException(409, '此环境未通过 systemd 启动')
        async with lock:
            if pending:
                raise HTTPException(409, '服务正在重启，请等待连接恢复')
            pending = True
            try:
                await restart_service()
            except (OSError, RuntimeError) as error:
                pending = False
                raise HTTPException(503, str(error)) from None
        return {'accepted': True}
