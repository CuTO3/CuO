'''
本文件用途：Inbound OneBot events only persist; no model or sending occurs here.

配置字段：
groups                               启用的群及数据库映射
self_id                              机器人账号标识
'''

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from uuid import UUID, uuid5

from psycopg import sql
from Core.clock import business_date, require_aware

TASK_NAMESPACE = UUID("75234efe-7d82-4b2d-a6ae-65078672cff8")


def stable_task_id(self_id, group_id, message_id, trigger_type):
    return str(uuid5(TASK_NAMESPACE, json.dumps([self_id, group_id, message_id, trigger_type], ensure_ascii=False, separators=(",", ":"))))


def _id(value, *, positive=True):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("invalid identity")
    result = str(value)
    if not result or not (result.isdecimal() if positive else result.lstrip("-").isdecimal()):
        raise ValueError("invalid identity")
    return result


async def receive_event(event, received_at, *, context):
    def outcome(status, reason=None, **extra):
        return {"status": status, "message_row_id": None, "task_ids": [], "cache_status": "not_applicable", "reason": reason, **extra}
    try:
        received_at = require_aware(received_at)
        if not isinstance(event, dict):
            return outcome("invalid", "invalid_event")
        if event.get('post_type') == 'notice':
            return await receive_notice(event, received_at, context=context)
        if event.get("post_type") not in ("message", "message_sent") or event.get("message_type") != "group":
            return outcome("ignored", "unsupported_event_type")
        group_id = _id(event.get("group_id"))
        self_id = _id(event.get("self_id"))
        user_id = _id(event.get("user_id"))
        message_id = _id(event.get("message_id"), positive=False)
        if group_id not in context.settings.groups:
            return outcome("ignored", "group_not_allowed")
        if self_id != context.settings.self_id:
            return outcome("invalid", "self_id_mismatch")
        sender = event.get("sender", {})
        if not isinstance(sender, dict) or (sender.get("user_id") is not None and _id(sender["user_id"]) != user_id):
            return outcome("invalid", "sender_mismatch")
        if "time" in event:
            timestamp = event["time"]
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
                raise ValueError("invalid time")
            sent_at = datetime.fromtimestamp(timestamp, timezone.utc)
            time_source = "event"
        else:
            sent_at, time_source = received_at, "received"
        segments = event.get("message")
        if not isinstance(segments, list) or any(not isinstance(seg, dict) or not isinstance(seg.get("type"), str) or not isinstance(seg.get("data"), dict) for seg in segments):
            raise ValueError("invalid message segments")
        nickname = next((sender[key].strip() for key in ("card", "nickname") if isinstance(sender.get(key), str) and sender[key].strip()), None)
        raw_text = "".join(seg["data"].get("text", "") for seg in segments if seg["type"] == "text" and isinstance(seg["data"].get("text"), str))
        at_bot = any(seg["type"] == "at" and str(seg["data"].get("qq")) == self_id for seg in segments)
        request_text = "".join(seg["data"].get("text", "") if seg["type"] == "text" else "" if seg["type"] == "at" and str(seg["data"].get("qq")) == self_id else "@" + str(seg["data"].get("qq")) if seg["type"] == "at" else {"image": "[图片]", "face": "[表情]", "reply": "[回复]", "record": "[语音]", "video": "[视频]"}.get(seg["type"], "[" + seg["type"] + "]") for seg in segments)
    except (ValueError, OverflowError, OSError, TypeError):
        return outcome("invalid", "invalid_identity_time_or_segments")

    db = context.db
    day = business_date(sent_at)
    task_ids = []
    async with db.transaction(group_id) as tx:
        # Serializes receiver mutations even if direct callers bypass the inbound queue.
        await db.fetch(group_id, "SELECT pg_advisory_xact_lock(hashtextextended(%s, 42))", (group_id,), transaction=tx)
        existing = await db.read("messages", group_id=group_id, filters={"message_id": message_id}, limit=1, transaction=tx)
        if existing:
            return outcome("duplicate", message_row_id=existing[0]["id"])
        members = await db.read("members", group_id=group_id, filters={"user_id": user_id}, limit=1, transaction=tx)
        member = members[0] if members else None
        display_nickname = nickname or (member["nickname"] if member else "群友")
        previous = await db.fetch(group_id, sql.SQL("SELECT sent_at,id FROM {} WHERE user_id=%s AND processing->'receiver'->>'nickname_observed'='true' ORDER BY sent_at DESC,id DESC LIMIT 1").format(db.table(group_id, "messages")), (user_id,), transaction=tx)
        observed = nickname is not None and user_id != self_id and (not previous or sent_at >= previous[0]["sent_at"])
        processing = {"raw_event": event, "receiver": {"request_text": request_text, "at_bot": at_bot, "time_source": time_source, "nickname_observed": observed, "receiver_version": 1, "self_message": user_id == self_id}, "media": [{"type": seg["type"], "data": seg["data"], "status": "pending"} for seg in segments if seg["type"] in ("image", "record", "video", "file")]}
        row = (await db.write("messages", [{"message_id": message_id, "sent_at": sent_at, "received_at": received_at, "business_date": day, "user_id": user_id, "nickname": display_nickname, "text": raw_text, "segments": segments, "processing": processing}], group_id=group_id, transaction=tx))[0]
        first_trusted = False
        if member is None:
            await db.write("members", [{"user_id": user_id, "nickname": display_nickname}], group_id=group_id, transaction=tx)
            first_trusted = observed
        elif observed and member["nickname"] == "群友" and not member.get("sheet_name") and not any(member.get("slots", [])):
            prior_logs = await db.read("log", group_id=group_id, filters={"user_id": user_id, "request_type": "memento"}, limit=1, transaction=tx)
            first_trusted = not prior_logs
        if observed and (member is None or nickname != member["nickname"] or first_trusted):
            await db.write("members", [{"user_id": user_id, "nickname": nickname, "updated_at": received_at}], group_id=group_id, mode="update", key_fields=("user_id",), transaction=tx)
            task_id = stable_task_id(self_id, group_id, message_id, "nickname_observed")
            params = {"old_nickname": member["nickname"] if member else None, "new_nickname": nickname, "is_initial": member is None or first_trusted, "observation_message_id": message_id, "observation_row_id": row["id"], "observed_at": sent_at.isoformat(), "self_id": self_id, "queue": {"batch_seq": row["id"], "order": 0}}
            await db.write("log", [_task(task_id, "memento", params, row, received_at)], group_id=group_id, transaction=tx)
            task_ids.append(task_id)
        if at_bot and user_id != self_id:
            task_id = stable_task_id(self_id, group_id, message_id, "message")
            params = {"request_text": request_text.strip(), "message_row_id": row["id"], "snapshot_seq": row["id"], "segments": segments, "self_id": self_id, "queue": {"batch_seq": row["id"], "order": 2}}
            await db.write("log", [_task(task_id, "message", params, row, received_at)], group_id=group_id, transaction=tx)
            task_ids.append(task_id)
        if user_id != self_id and any(s['type']=='image' for s in segments):
            task_id=stable_task_id(self_id,group_id,message_id,'media_describe')
            await db.write('log',[_task(task_id,'media_describe',{'message_row_id':row['id'],'queue':{'batch_seq':row['id'],'order':1}},row,received_at)],group_id=group_id,transaction=tx)
            task_ids.append(task_id)
        if user_id == self_id:
            sources=await db.fetch(group_id,sql.SQL("SELECT task_id,params,request_type,result FROM {} WHERE business_status='completed' AND result->'actions' IS NOT NULL").format(db.table(group_id,'log')),transaction=tx)
            source=next((s for s in sources if any(str((a.get('receipt') or {}).get('message_id'))==message_id for a in s['result'].get('actions',[]))),None)
            processing['source_task_id']=str(source['task_id']) if source else None
            await db.write('messages',[{'id':row['id'],'generated_by':source['params'].get('_opt',source['request_type']) if source else 'bot','processing':processing}],group_id=group_id,mode='update',key_fields=('id',),transaction=tx)
    cache_status = "ready"
    try:
        await context.cache.refresh_day(group_id, day)
    except Exception:
        cache_status = "dirty"
    if context.queue:
        context.queue.wake()
    return outcome("accepted", message_row_id=row["id"], task_ids=task_ids, cache_status=cache_status)


async def receive_notice(event, received_at, *, context):
    # Only an explicit group-card notice is a trusted nickname observation.
    if event.get('notice_type') != 'group_card':return {'status':'ignored','reason':'unsupported_notice'}
    gid=_id(event.get('group_id'));uid=_id(event.get('user_id'));sid=_id(event.get('self_id'))
    if gid not in context.settings.groups or sid!=context.settings.self_id or uid==sid:return {'status':'ignored'}
    name=event.get('card_new')
    if not isinstance(name,str) or not name.strip():return {'status':'invalid','reason':'invalid_nickname'}
    import hashlib
    digest=hashlib.sha256(json.dumps(event,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    identity=str(event.get('notice_id') or digest)
    task_id=stable_task_id(sid,gid,identity,'group_card_v1')
    triggered=datetime.fromtimestamp(event['time'],timezone.utc) if type(event.get('time')) in (int,float) else received_at
    async with context.db.transaction(gid) as tx:
        existing=await context.db.read('log',group_id=gid,filters={'task_id':task_id},transaction=tx)
        if existing:return {'status':'duplicate'}
        members=await context.db.read('members',group_id=gid,filters={'user_id':uid},transaction=tx)
        old=members[0] if members else None
        if old and old['updated_at']>triggered:return {'status':'ignored','reason':'stale_notice'}
        await context.db.write('members',[{'user_id':uid,'nickname':name.strip(),'updated_at':received_at}],group_id=gid,mode='upsert',key_fields=('user_id',),transaction=tx)
        await context.db.write('log',[{'task_id':task_id,'created_at':received_at,'triggered_at':triggered,'business_date':business_date(triggered),'request_type':'memento','user_id':uid,'params':{'new_nickname':name.strip(),'old_nickname':old['nickname'] if old else None,'is_initial':old is None,'observed_at':triggered.isoformat(),'notice':event,'dedup_version':1}}],group_id=gid,transaction=tx)
    if context.queue:context.queue.wake()
    return {'status':'accepted','task_ids':[task_id]}


def _task(task_id, request_type, params, row, received_at):
    return {"task_id": task_id, "request_type": request_type, "triggered_at": row["sent_at"], "created_at": received_at, "business_date": row["business_date"], "user_id": row["user_id"], "message_id": row["message_id"], "original_text": row["text"], "params": params, "status": "pending", "business_status": "pending", "step": "queued"}
