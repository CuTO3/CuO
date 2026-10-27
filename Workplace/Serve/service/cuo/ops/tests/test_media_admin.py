import asyncio
import copy
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from PIL import Image

from Integration.console.routes import install
from Integration.console.media import Annotation, annotate, revision, save_annotation
from Function.summary.son_function import image_processor
from Function.summary.son_function.normalize_messages import normalize_messages
from Core.cache import CacheManager


def test_annotation_history_and_version():
    old = {"status": "unavailable", "description": "图片暂不可用", "error_code": "ModelUnavailable"}
    first = annotate(old, Annotation(description="一只白猫。", note="校对文字", expected_version=revision(old)))
    assert first["machine_result"] == old
    assert first["status"] == "ready" and first["manually_reviewed"]
    assert "error_code" not in first
    assert "annotation_history" not in old
    assert revision({**old, "original_hash": "a" * 64}) == revision(old)
    with pytest.raises(HTTPException) as error:
        annotate(first, Annotation(description="并发修改", expected_version=revision(old)))
    assert error.value.status_code == 409
    second = annotate(first, Annotation(description="两只白猫。", expected_version=revision(first)))
    assert second["machine_result"] == old
    assert len(second["annotation_history"]) == 2
    assert second["annotation_history"][0]["description"] == "一只白猫。"
    with pytest.raises(HTTPException):
        annotate(old, Annotation(description="  ", expected_version=revision(old)))


async def seed(ctx):
    instant = datetime(2026, 10, 27, 3, tzinfo=timezone.utc)
    segments = [{"type": "image", "data": {"url": "https://gchat.qpic.cn/test-only", "file": "test.png"}},
                {"type": "text", "data": {"text": "private chat text"}},
                {"type": "image", "data": {"url": "https://gchat.qpic.cn/test-only-2"}}]
    key = image_processor.segment_key(segments[0])
    root = ctx.settings.data_root / "groups" / ctx.gid / "media"
    root.mkdir(parents=True)
    temp = root / "fixture.png"
    Image.new("RGB", (16, 16), "white").save(temp)
    digest = hashlib.sha256(temp.read_bytes()).hexdigest()
    temp.rename(root / digest)
    item = {"status": "unavailable", "description": "图片暂不可用", "hash": digest, "error_code": "ModelUnavailable"}
    row = (await ctx.db.write("messages", [{"message_id": "123", "user_id": "100", "nickname": "合成样例", "sent_at": instant,
        "business_date": instant.date(), "text": "private chat text", "segments": segments,
        "processing": {"raw_event": {"preserved": True}, "media_descriptions": {key: item}}}], group_id=ctx.gid))[0]
    return row, key, item


def app_for(ctx):
    app = FastAPI()
    app.state.ctx = ctx
    install(app)
    return app


async def test_image_routes_and_database_persistence(ctx):
    row, key, original = await seed(ctx)
    cache = CacheManager(ctx.settings, ctx.db)
    ctx.db.set_cache(cache)
    base = f"/console/api/images/{ctx.gid}/{row['id']}/{key}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(ctx)), base_url="http://test", headers={"X-Cuo-Request":"console"}) as client:
        assert (await client.get(base + "/original")).status_code == 401
        assert (await client.post("/console/api/login", json={"token": "admin-test"})).status_code == 200
        response = await client.get(f"/console/api/images/{ctx.gid}?limit=1")
        assert response.status_code == 200
        assert response.json()["total"] == 2 and len(response.json()["items"]) == 1
        assert "private chat text" not in response.text and "qpic" not in response.text
        assert (await client.get(f"/console/api/images/{ctx.gid}?offset=1&limit=1")).json()["items"][0]["image_index"] == 3
        before = (await client.get(base)).json()
        image = await client.get(base + "/original")
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        assert image.content.startswith(b"\x89PNG")
        assert (await client.get(base)).json()["version"] == before["version"]
        response = await client.put(base, json={"description":"白色方形图片。", "note":"人工核对", "expected_version":before["version"]})
        assert response.status_code == 200 and response.json()["reviewed"]
        assert response.json()["machine_error"] == "ModelUnavailable"
        assert (await client.put(base, json={"description":"旧版本", "expected_version":before["version"]})).status_code == 409
        assert (await client.put(base, json={"description":"x" * 4001, "expected_version":before["version"]})).status_code == 422
        assert (await client.get(base.replace(ctx.gid, ctx.other))).status_code == 404
        assert (await client.get(base.replace(key, "0" * 64))).status_code == 404
        assert (await client.get(f"/console/api/images/{ctx.gid}?offset=-1")).status_code == 422
    stored = (await ctx.db.read("messages", group_id=ctx.gid, filters={"id":row["id"]}))[0]
    assert stored["text"] == "private chat text" and stored["processing"]["raw_event"]["preserved"]
    assert stored["processing"]["media_descriptions"][key]["machine_result"] == original
    cached = await cache.read_messages(ctx.gid, row["business_date"])
    assert cached[0]['media'][0]['description'] == "白色方形图片。"
    assert 'processing' not in cached[0]
    records, _ = await normalize_messages([stored], ctx, ctx.gid)
    assert records[0]["media"][0]["description"] == "白色方形图片。"


async def test_inflight_model_cannot_overwrite_annotation(ctx, monkeypatch):
    row, key, original = await seed(ctx)
    started, release = asyncio.Event(), asyncio.Event()
    async def download(url, root):
        return root / original["hash"], original["hash"]
    async def describe(images, prompt):
        started.set()
        await release.wait()
        return "过时的机器结果"
    monkeypatch.setattr(image_processor, "download", download)
    ctx.model.describe_images = describe
    pending = asyncio.create_task(image_processor.describe_image(row["segments"][0], ctx, ctx.gid, row))
    await asyncio.wait_for(started.wait(), 5)
    try:
        await save_annotation(ctx, ctx.gid, row["id"], key, Annotation(description="人工更准确的描述", expected_version=revision(original)))
    finally:
        release.set()
    result = await pending
    assert result["description"] == "人工更准确的描述"
    stored = (await ctx.db.read("messages", group_id=ctx.gid, filters={"id":row["id"]}))[0]
    assert stored["processing"]["media_descriptions"][key]["manually_reviewed"]


async def test_failed_model_preserves_original_reference(ctx, monkeypatch):
    row, key, original = await seed(ctx)
    async def download(url, root):return root / original["hash"], original["hash"]
    async def describe(images, prompt):raise RuntimeError("unavailable")
    monkeypatch.setattr(image_processor, "download", download)
    ctx.model.describe_images = describe
    result = await image_processor.describe_image(row["segments"][0], ctx, ctx.gid, row)
    assert result["status"] == "unavailable" and result["hash"] == original["hash"]


async def test_original_download_merges_without_changing_revision(ctx, monkeypatch):
    from Integration.console import media as media_admin
    row, key, original = await seed(ctx)
    row["processing"]["media_descriptions"][key].pop("hash")
    await ctx.db.write("messages", [{"id":row["id"], "processing":row["processing"]}], group_id=ctx.gid, mode="update", key_fields=("id",))
    files = list((ctx.settings.data_root / "groups" / ctx.gid / "media").iterdir())
    async def download(url, root):return files[0], files[0].name
    monkeypatch.setattr(media_admin, "download", download)
    base=f"/console/api/images/{ctx.gid}/{row['id']}/{key}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(ctx)), base_url="http://test", headers={"X-Cuo-Request":"console"}) as client:
        await client.post("/console/api/login", json={"token":"admin-test"})
        before=(await client.get(base)).json()
        assert (await client.get(base+"/original")).status_code == 200
        assert (await client.get(base)).json()["version"] == before["version"]
