"""Same-origin operator console; no secrets returned to browsers."""
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
    app.state.console_sessions = {}
    app.state.console_attempts = []
    lock = asyncio.Lock()
    root = Path(__file__).resolve().parents[3] / "frontend"
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

    def settings_payload(ctx):
        data = {key: getattr(ctx.settings, key) for key in ConsoleSettings.model_fields}
        version = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        return {"values": data, "version": version}

    @app.get("/console/api/settings")
    async def settings(request: Request):
        ctx = require(request)
        return {**settings_payload(ctx), "model_protocol": ctx.settings.model_protocol,
                "vision_configured": bool(ctx.settings.vision_model_name and ctx.settings.vision_api_key),
                "self_id": ctx.settings.self_id}

    @app.put("/console/api/settings")
    async def update_settings(request: Request):
        ctx = require(request)
        body = await request.body()
        if len(body) > 4096:
            raise HTTPException(413)
        try:
            payload = json.loads(body)
            values = ConsoleSettings.model_validate(payload["values"])
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, "参数格式或范围不正确") from None
        async with lock:
            if payload.get("version") != settings_payload(ctx)["version"]:
                raise HTTPException(409, "配置已被其他会话修改，请刷新后重试")
            path = getattr(ctx.settings, "config_root", ctx.settings.data_root) / "console-settings.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(values.model_dump_json(indent=2), encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            for key, value in values.model_dump().items():
                setattr(ctx.settings, key, value)
            ctx.model.client.timeout = httpx.Timeout(values.model_timeout)
            ctx.onebot.timeout = values.onebot_timeout
        return settings_payload(ctx)

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
