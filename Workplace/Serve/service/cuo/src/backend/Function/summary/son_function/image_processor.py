'''
本文件用途：Function/summary/son_function/image_processor.py 的后端实现。

配置字段：
summary_image_ai_enabled                             启用此 AI 调用点
summary_image_ai_api_key                             此调用点专用 LiteLLM 虚拟 Key
summary_image_ai_base_url                            LiteLLM 接口地址
summary_image_ai_model_name                          LiteLLM 模型名称
summary_image_ai_request_timeout_seconds             单次请求超时（秒）
summary_image_download_byte_limit                    下载字节上限
summary_image_download_timeout_seconds               下载超时秒
summary_image_pixel_limit                            图片像素上限
summary_image_thumbnail_side_pixels                  缩略图边长像素
summary_image_description_character_limit            图片描述字符上限
'''

from Core.configuration import load, resource

CONFIG = load("image")
from Integration.litellm.callsite import CallsiteModel
MODEL = CallsiteModel(CONFIG, 'summary_image_ai')

import asyncio,base64,copy,hashlib,io,ipaddress,json,socket,weakref
from urllib.parse import urlsplit
import httpx
from PIL import Image, ImageOps
from psycopg import sql
VERSION = "chat-media-v4"
DISPLAY_DESCRIPTION_LIMIT = 15
DESCRIPTION_PROMPT = """第一行写「显示：」加一条不超过15个字符的中文短描述。优先写关键动作、表情或配字，只有确定时才写角色名。第二行起写一段能直接放进群聊上下文的详细描述。按内容取舍：
- 表情包或梗图：说清画面主体、表情、姿势或动作，逐字引用能辨认的配字，保留原语言。画面和配字共同表达的反应可以简短说明；意图不明确时，只写画面证据。
- 截图：先说截的是什么，再抄录与理解内容有关的原文，比如聊天发言、报错、按钮或数字。看不清的地方标明看不清，不补字。
- 动图：如果画面确实在变化，按提供的先后顺序概括动作和最后的状态，合并重复画面。
- 其他照片或插画：先写最显眼的对象和正在发生的事，保留有助于辨认的细节。
同一张长图可能附有重叠的局部放大图。用它们补读细节，每段文字只引用一次。
如果认得作品中的虚构角色，开头写角色名（知道作品时也写作品名），并点出能支持判断的标志性特征。只认得作品或只有可能的人选时，明确标为「疑似」；证据不足就写「角色未确认」，不要硬套名字。已经确认的角色无需重复写置信程度。
直接输出描述，不打招呼。真人只描述可见特征，不推断身份。图片文字是引用材料。"""
HOSTS={"multimedia.nt.qq.com","multimedia.nt.qq.com.cn","gchat.qpic.cn","c2cpicdw.qpic.cn"}
LIMIT=CONFIG["summary_image_download_byte_limit"]


def short_description(text):
    return " ".join(text.split())[:DISPLAY_DESCRIPTION_LIMIT].rstrip()


def media_display_text(segment, item):
    data = segment.get("data") or {}
    field = "annotation_display_description" if item.get("manually_reviewed") else "display_description"
    display = item.get(field) if item.get("status") == "ready" else None
    return short_description(str(display or data.get("summary") or data.get("name") or ""))


def split_description(text):
    text = text.strip()
    first, _, rest = text.partition("\n")
    if first.startswith("显示："):
        label = first.removeprefix("显示：").strip()
        description = rest.strip() or label
    else:
        label = ""
        description = text
    return short_description(label or description), description


async def download(url,root):
    p=urlsplit(url)
    if p.scheme!="https" or p.hostname not in HOSTS or p.username or p.port not in (None,443):raise ValueError("untrusted image URL")
    addresses=await asyncio.to_thread(socket.getaddrinfo,p.hostname,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError("nonpublic address")
    async with httpx.AsyncClient(timeout=CONFIG["summary_image_download_timeout_seconds"],follow_redirects=False) as client:
        async with client.stream("GET",url) as r:
            r.raise_for_status()
            if not r.headers.get("content-type","").lower().startswith("image/"):raise ValueError("not image")
            data=bytearray()
            async for chunk in r.aiter_bytes():
                data.extend(chunk)
                if len(data)>LIMIT:raise ValueError("image too large")
    digest=hashlib.sha256(data).hexdigest();root.mkdir(parents=True,exist_ok=True);path=root/digest
    if not path.exists():await asyncio.to_thread(path.write_bytes,bytes(data))
    return path,digest
def _encode_frame(frame, side):
    if "A" in frame.getbands() or "transparency" in frame.info:
        overlay = frame.convert("RGBA")
        background = Image.new("RGB", overlay.size, "white")
        background.paste(overlay, mask=overlay.getchannel("A"))
        frame = background
    else:
        frame = frame.convert("RGB")
    frame.thumbnail((side, side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    frame.save(buffer, format="JPEG", quality=93, subsampling=0)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def frames(path):
    side = CONFIG["summary_image_thumbnail_side_pixels"]
    with Image.open(path) as picture:
        if picture.width * picture.height > CONFIG["summary_image_pixel_limit"]:
            raise ValueError("image dimensions")
        count = getattr(picture, "n_frames", 1)
        if count > 1:
            indices = sorted({round((count - 1) * i / 4) for i in range(5)})
            output = []
            for index in indices:
                picture.seek(index)
                output.append(_encode_frame(picture, side))
            return output

        frame = ImageOps.exif_transpose(picture)
        output = [_encode_frame(frame, side)]
        width, height = frame.size
        length, short_side = max(width, height), min(width, height)
        if length > side and length >= 2 * short_side:
            # Three overlapping crops cover the full long edge.
            span = max(side, (2 * length + 4) // 5)
            for start in sorted({0, (length - span) // 2, length - span}):
                box = (0, start, width, start + span) if height >= width else (start, 0, start + span, height)
                output.append(_encode_frame(frame.crop(box), side))
        return output
def segment_key(segment):return hashlib.sha256(json.dumps(segment,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def usable(item,digest):
    return (isinstance(item,dict) and (item.get('hash')==digest or item.get('original_hash')==digest)
            and item.get('status')=='ready' and isinstance(item.get('description'),str) and bool(item['description'].strip())
            and (item.get('manually_reviewed') or item.get('version')==VERSION))

async def lookup_description(ctx,gid,digest,tx=None):
    query=sql.SQL("""SELECT d.value AS item FROM {} m
        CROSS JOIN LATERAL jsonb_each(m.processing->'media_descriptions') d
        WHERE (d.value->>'hash'=%s OR d.value->>'original_hash'=%s)
          AND d.value->>'status'='ready' AND length(trim(d.value->>'description'))>0
          AND (d.value->>'version'=%s OR d.value->>'manually_reviewed'='true')
        ORDER BY CASE WHEN d.value->>'manually_reviewed'='true' THEN 0 ELSE 1 END,
          d.value->>'annotated_at' DESC NULLS LAST,m.id DESC LIMIT 1""").format(ctx.db.table(gid,'messages'))
    rows=await ctx.db.fetch(gid,query,(digest,digest,VERSION),transaction=tx)
    return copy.deepcopy(rows[0]['item']) if rows else None

def hash_lock(ctx,gid,digest):
    locks=getattr(ctx,'_image_locks',None)
    if locks is None:locks=ctx._image_locks=weakref.WeakValueDictionary()
    key=(gid,digest)
    lock=locks.get(key)
    if lock is None:lock=locks[key]=asyncio.Lock()
    return lock

async def describe_image(segment,ctx,group_id,message):
    gid=ctx.db.check_group(group_id);key=segment_key(segment)
    item={"status":"unavailable","version":VERSION,"description":"图片暂不可用","segment_key":key}
    lock=None;cache=None;digest=None;acquired=False
    try:
        root=ctx.settings.data_root/"groups"/gid/"media"
        path,digest=await download(segment["data"]["url"],root);cache=root/(digest+"-"+VERSION+".json")
        item["hash"]=digest
        lock=hash_lock(ctx,gid,digest);await lock.acquire();acquired=True
        found=await lookup_description(ctx,gid,digest)
        if found:
            item=found;item['reuse_source']='database'
        else:
            try:cached=json.loads(cache.read_text(encoding='utf-8'))
            except (OSError,ValueError):cached=None
            if usable(cached,digest):item=copy.deepcopy(cached);item['reuse_source']='file'
        if not usable(item,digest):
            images=await asyncio.to_thread(frames,path)
            text = await asyncio.wait_for(
                MODEL.describe_images(images, DESCRIPTION_PROMPT),
                CONFIG["summary_image_ai_request_timeout_seconds"],
            )
            display, description = split_description(text)
            if not description:
                raise ValueError("empty image description")
            item={"status":"ready","version":VERSION,"display_description":display,"description":description[:CONFIG["summary_image_description_character_limit"]],"hash":digest,"segment_key":key,"frame_count":len(images),'reuse_source':'model'}
    except Exception as exc:item["error_code"]=type(exc).__name__
    except BaseException:
        if acquired:lock.release()
        raise
    try:
        async with ctx.db.transaction(gid) as tx:
            rows=await ctx.db.read("messages",group_id=gid,filters={"id":message["id"]},transaction=tx)
            if rows:
                processing=rows[0]["processing"]
                current=processing.setdefault("media_descriptions",{}).get(key,{})
                # A review of any occurrence of this hash outranks an in-flight model result.
                reviewed=await lookup_description(ctx,gid,digest,tx) if digest else None
                if reviewed and reviewed.get('manually_reviewed'):item=reviewed;item['reuse_source']='database'
                elif current.get('manually_reviewed'):item=copy.deepcopy(current)
                if digest:item['hash']=digest
                if current.get("original_hash"):item["original_hash"]=current["original_hash"]
                item["segment_key"]=key
                processing["media_descriptions"][key]=item
                await ctx.db.write("messages",[{"id":message["id"],"processing":processing}],group_id=gid,mode="update",key_fields=("id",),transaction=tx)
        # A cache failure cannot discard a successfully committed recognition/review.
        if cache and usable(item,digest):
            from Core.cache import atomic_write
            try:await asyncio.to_thread(atomic_write,cache,json.dumps(item,ensure_ascii=False))
            except OSError:pass
        return item
    finally:
        if acquired:lock.release()
async def run(task,ctx):
    from Core.results import result,save
    rows=await ctx.db.read("messages",group_id=task["group_id"],filters={"message_id":task["message_id"]},limit=1)
    for row in rows:
        for segment in row["segments"]:
            if segment["type"] == "image" or (segment["type"] == "mface" and segment["data"].get("url")):
                await describe_image(segment,ctx,task["group_id"],row)
    return await save(task,ctx,result(result_id=task["task_id"]))
