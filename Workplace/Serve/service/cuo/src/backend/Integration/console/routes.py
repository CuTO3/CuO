'''
本文件用途：Same-origin operator console; no secrets returned to browsers.

配置字段：
admin_token                          控制台访问凭据
data_root                            私有运行数据根目录
model_name                           模型名称
model_protocol                       模型接口协议
self_id                              机器人账号标识
vision_api_key                       图片识别接口密钥
vision_model_name                    图片识别模型名称
'''

import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from psycopg import sql


from .settings import ConsoleSettings


def authenticated(request):
    token = request.cookies.get("cuo_session", "")
    sessions = getattr(request.app.state, "console_sessions", {})
    return bool(token and sessions.get(token, 0) > time.monotonic()
                and request.headers.get("x-cuo-request") == "console")


def require(request):
    if not authenticated(request):
        raise HTTPException(401, "请先登录管理台")
    return request.app.state.ctx


def install(app):
    from Integration.console.media import install as install_media
    install_media(app, require)
    from Integration.console.configuration import install as install_configuration
    install_configuration(app, require)
    app.state.console_sessions = {}
    app.state.console_attempts = []
    lock = asyncio.Lock()
    from Core.configuration import load, resource
    root = resource(load("console")["console_frontend_directory"])
    app.mount("/console/assets", StaticFiles(directory=root), name="console-assets")

    @app.middleware("http")
    async def console_headers(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/console", "/admin")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.get("/console/")
    async def index():
        return FileResponse(root / "index.html")

    @app.post("/console/api/login")
    async def login(request: Request):
        if request.headers.get("x-cuo-request") != "console":
            raise HTTPException(403)
        current = time.monotonic()
        attempts = app.state.console_attempts
        attempts[:] = [x for x in attempts if current - x < 60]
        if len(attempts) >= 10:
            raise HTTPException(429, "尝试过于频繁，请一分钟后重试")
        attempts.append(current)
        body = await request.body()
        if len(body) > 2048:
            raise HTTPException(413)
        try:
            value = json.loads(body).get("token", "")
        except (ValueError, AttributeError):
            raise HTTPException(422) from None
        expected = app.state.ctx.settings.admin_token
        if not isinstance(value, str) or not expected or not hmac.compare_digest(value.encode(), expected.encode()):
            raise HTTPException(401, "管理密钥不正确")
        sessions = app.state.console_sessions
        for key in list(sessions):
            if sessions[key] < current:
                del sessions[key]
        if len(sessions) >= 20:
            sessions.pop(next(iter(sessions)))
        token = secrets.token_urlsafe(32)
        sessions[token] = current + 28800
        response = JSONResponse({"ok": True})
        response.set_cookie("cuo_session", token, httponly=True, samesite="strict", max_age=28800,
                            secure=request.url.scheme == "https", path="/")
        return response

    @app.post("/console/api/logout")
    async def logout(request: Request):
        require(request)
        app.state.console_sessions.pop(request.cookies.get("cuo_session"), None)
        response = JSONResponse({"ok": True})
        response.delete_cookie("cuo_session", path="/")
        return response

    @app.get("/console/api/settings")
    async def settings(request: Request):
        require(request)
        return {"migration_required": True, "configuration_url": "/console/api/configuration",
                "message": "模型配置已按调用点拆分，请使用模块配置接口；保存后重启。"}

    @app.put("/console/api/settings")
    async def update_settings(request: Request):
        require(request)
        raise HTTPException(409, "旧共享设置接口已停用，请使用 /console/api/configuration/{模块名}")

    @app.get("/console/api/overview/{gid}")
    async def overview(gid: str, request: Request):
        ctx = require(request)
        if gid not in ctx.db.groups:
            raise HTTPException(404)
        counts = {}
        for table in ("members", "messages", "summaries", "divinations"):
            rows = await ctx.db.fetch(gid, sql.SQL("SELECT count(*) AS n FROM {}").format(ctx.db.table(gid, table)))
            counts[table] = rows[0]["n"]
        states = await ctx.db.fetch(gid, sql.SQL("SELECT status, count(*) AS n FROM {} GROUP BY status").format(ctx.db.table(gid, "log")))
        daily = await ctx.db.fetch(gid, sql.SQL("SELECT business_date::text AS day,count(*) AS n FROM {} WHERE business_date >= (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date - 6 GROUP BY business_date ORDER BY business_date").format(ctx.db.table(gid, "messages")))
        return {"counts": counts, "tasks": {r["status"]: r["n"] for r in states}, "daily": daily,
                "ready": ctx.ready, "connected": ctx.onebot.connected,
                "model": ctx.settings.model_name, "inbound": app.state.inbound.qsize()}
