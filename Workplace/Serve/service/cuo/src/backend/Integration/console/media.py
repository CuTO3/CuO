'''
本文件用途：Image-only views and reviewed descriptions, backed by PostgreSQL JSONB.

配置字段：
data_root                            私有运行数据根目录
'''

import asyncio
import copy
import hashlib
import json
import re
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field
from psycopg import sql
from Function.summary.son_function.image_processor import segment_key, download, VERSION
from Core.clock import now


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    description: str = Field(min_length=1, max_length=4000)
    note: str = Field(default="", max_length=1000)
    expected_version: str = Field(pattern=r"^[a-f0-9]{64}$")


def revision(item):
    # Fetching an original must not invalidate the editor's optimistic lock.
    data = {k: v for k, v in item.items() if k not in {"hash", "original_hash", "segment_key", "frame_count"}}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def annotate(item, payload):
    if not payload.description.strip():
        raise HTTPException(422, "请填写图片描述")
    if revision(item) != payload.expected_version:
        raise HTTPException(409, "此图片的识别结果已更新。请重新载入后再保存，当前输入不会被覆盖。")
    value = copy.deepcopy(item)
    if "machine_result" not in value:
        value["machine_result"] = copy.deepcopy(item)
    history = value.setdefault("annotation_history", [])
    history.append({"description": payload.description.strip(), "note": payload.note.strip(),
                    "at": now().isoformat(), "actor": "administrator", "revision": len(history) + 1})
    value.update(description=payload.description.strip(), status="ready", version=VERSION,
                 manually_reviewed=True, annotation_note=payload.note.strip(), annotated_at=history[-1]["at"])
    value.pop("error_code", None)
    return value


def record(row, segment, index):
    key = segment_key(segment)
    item = row.get("processing", {}).get("media_descriptions", {}).get(key, {})
    machine = item.get("machine_result", item)
    return {"message_row_id": row["id"], "segment_key": key, "image_index": index,
            "sent_at": row["sent_at"].isoformat(), "version": revision(item),
            "status": item.get("status", "pending"), "description": item.get("description", ""),
            "reviewed": bool(item.get("manually_reviewed")), "note": item.get("annotation_note", ""),
            "annotated_at": item.get("annotated_at"), "error_code": item.get("error_code"),
            "machine_description": machine.get("description", ""),
            "machine_status": machine.get("status", "pending"), "machine_error": machine.get("error_code"),
            "history": item.get("annotation_history", []),
            "original_cached": bool(item.get("hash") or item.get("original_hash"))}


async def find(ctx, gid, mid, key, tx=None):
    if gid not in ctx.db.groups or not re.fullmatch(r"[a-f0-9]{64}", key):
        raise HTTPException(404, "图片不存在")
    query = sql.SQL("SELECT * FROM {} WHERE id=%s" + (" FOR UPDATE" if tx else "")).format(ctx.db.table(gid, "messages"))
    rows = await ctx.db.fetch(gid, query, (mid,), transaction=tx)
    if rows:
        for index, segment in enumerate(rows[0]["segments"], 1):
            if segment.get("type") == "image" and segment_key(segment) == key:
                return rows[0], segment, index
    raise HTTPException(404, "图片不存在")


async def save_annotation(ctx, gid, mid, key, payload):
    if gid not in ctx.db.groups:
        raise HTTPException(404)
    async with ctx.db.transaction(gid) as tx:
        row, segment, index = await find(ctx, gid, mid, key, tx)
        processing = row["processing"]
        entries = processing.setdefault("media_descriptions", {})
        entries[key] = annotate(entries.get(key, {}), payload)
        entries[key]["segment_key"] = key
        await ctx.db.write("messages", [{"id": mid, "processing": processing}], group_id=gid,
                           mode="update", key_fields=("id",), transaction=tx)
        digest=entries[key].get('hash') or entries[key].get('original_hash')
        if digest:await propagate_annotation(ctx,gid,digest,entries[key],tx)
        output=record(row, segment, index)
    if isinstance(digest,str) and re.fullmatch(r'[a-f0-9]{64}',digest):
        from Core.cache import atomic_write
        path=ctx.settings.data_root/'groups'/gid/'media'/(digest+'-'+VERSION+'.json')
        try:await asyncio.to_thread(atomic_write,path,json.dumps(entries[key],ensure_ascii=False))
        except OSError:pass
    return output


async def propagate_annotation(ctx,gid,digest,review,tx):
    """Make a human correction effective for every known occurrence in this group."""
    query=sql.SQL("""SELECT * FROM {} m WHERE EXISTS
        (SELECT FROM jsonb_each(m.processing->'media_descriptions') d
         WHERE d.value->>'hash'=%s OR d.value->>'original_hash'=%s) FOR UPDATE""").format(ctx.db.table(gid,'messages'))
    rows=await ctx.db.fetch(gid,query,(digest,digest),transaction=tx)
    changed=0
    for row in rows:
        entries=row['processing']['media_descriptions'];dirty=False
        for key,item in entries.items():
            if digest not in (item.get('hash'),item.get('original_hash')):continue
            if item.get('manually_reviewed') and item.get('annotated_at')==review.get('annotated_at') and item.get('description')==review['description']:continue
            value=copy.deepcopy(item)
            value.setdefault('machine_result',copy.deepcopy(item))
            history=value.setdefault('annotation_history',[])
            latest=copy.deepcopy(review['annotation_history'][-1]);latest['revision']=len(history)+1
            history.append(latest)
            value.update(description=review['description'],status='ready',version=VERSION,hash=digest,
                manually_reviewed=True,annotation_note=review.get('annotation_note',''),annotated_at=review['annotated_at'],segment_key=key)
            value.pop('error_code',None)
            entries[key]=value;dirty=True
        if dirty:
            await ctx.db.write('messages',[{'id':row['id'],'processing':row['processing']}],group_id=gid,mode='update',key_fields=('id',),transaction=tx)
            changed+=1
    return changed


def image_type(path):
    with Image.open(path) as picture:
        if picture.width * picture.height > 25_000_000:
            raise ValueError("image dimensions")
        mime = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp", "BMP": "image/bmp"}.get(picture.format)
        if not mime:
            raise ValueError("unsupported image format")
        picture.verify()
        return mime


def install(app, require):
    downloads = asyncio.Semaphore(3)

    @app.get("/console/api/images/{gid}")
    async def images(gid: str, request: Request, offset: int = 0, limit: int = 24):
        ctx = require(request)
        if gid not in ctx.db.groups:
            raise HTTPException(404)
        if offset < 0 or not 1 <= limit <= 48:
            raise HTTPException(422)
        source = sql.SQL("FROM {} m CROSS JOIN LATERAL jsonb_array_elements(m.segments) WITH ORDINALITY AS s(segment, ordinal) WHERE s.segment->>'type'='image'").format(ctx.db.table(gid, "messages"))
        async with ctx.db.transaction(gid) as tx:
            total = await ctx.db.fetch(gid, sql.SQL("SELECT count(*) AS n ") + source, transaction=tx)
            rows = await ctx.db.fetch(gid, sql.SQL("SELECT m.id,m.sent_at,m.processing,s.segment,s.ordinal ") + source +
                sql.SQL(" ORDER BY m.id DESC,s.ordinal LIMIT %s OFFSET %s"), (limit, offset), transaction=tx)
        return {"items": [record(r, r["segment"], r["ordinal"]) for r in rows],
                "total": total[0]["n"], "offset": offset, "limit": limit}

    @app.get("/console/api/images/{gid}/{mid}/{key}")
    async def detail(gid: str, mid: int, key: str, request: Request):
        ctx = require(request)
        row, segment, index = await find(ctx, gid, mid, key)
        return record(row, segment, index)

    @app.put("/console/api/images/{gid}/{mid}/{key}")
    async def update(gid: str, mid: int, key: str, request: Request):
        ctx = require(request)
        body = await request.body()
        if len(body) > 24000:
            raise HTTPException(413)
        try:
            payload = Annotation.model_validate_json(body)
        except ValueError:
            raise HTTPException(422, "描述最多 4000 字，备注最多 1000 字，请检查输入") from None
        return await save_annotation(ctx, gid, mid, key, payload)

    @app.get("/console/api/images/{gid}/{mid}/{key}/original")
    async def original(gid: str, mid: int, key: str, request: Request):
        ctx = require(request)
        row, segment, _ = await find(ctx, gid, mid, key)
        item = row["processing"].get("media_descriptions", {}).get(key, {})
        root = (ctx.settings.data_root / "groups" / gid / "media").resolve()
        digest = item.get("original_hash") or item.get("hash", "")
        path = root / digest if isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest) else None
        if path and (path.is_symlink() or not path.resolve().is_relative_to(root)):
            raise HTTPException(404, "原图不可用")
        if not path or not path.is_file():
            try:
                async with downloads:
                    path, digest = await asyncio.wait_for(download(segment.get("data", {}).get("url", ""), root), 30)
            except Exception:
                raise HTTPException(410, "未能获取原图：链接可能已失效或图片暂不可用，可稍后重试") from None
            async with ctx.db.transaction(gid) as tx:
                current, _, _ = await find(ctx, gid, mid, key, tx)
                current["processing"].setdefault("media_descriptions", {}).setdefault(key, {})["original_hash"] = digest
                await ctx.db.write("messages", [{"id": mid, "processing": current["processing"]}], group_id=gid,
                                   mode="update", key_fields=("id",), transaction=tx)
        try:
            mime = await asyncio.to_thread(image_type, path)
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            raise HTTPException(415, "原图格式不支持或文件已损坏") from None
        return FileResponse(path, media_type=mime, headers={"Content-Disposition": "inline", "Cache-Control": "no-store"})
