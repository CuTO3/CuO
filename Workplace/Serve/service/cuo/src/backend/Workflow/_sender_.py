from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import os
import shutil
from pathlib import Path
from uuid import UUID

from Integration.napcat.client import DeliveryUnknown, NotConnected
from Integration.napcat.text import split_text


def _group(group_id, context):
    if str(group_id) not in context.settings.groups:
        raise ValueError("invalid_target")
    return str(group_id)


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _segments(value):
    if not isinstance(value, list) or not value:
        raise ValueError("invalid_segments")
    clean = []
    for segment in value:
        if not isinstance(segment, dict) or set(segment) != {"type", "data"}:
            raise ValueError("invalid_segments")
        kind, data = segment["type"], segment["data"]
        if kind == "text" and isinstance(data, dict) and set(data) == {"text"} and isinstance(data["text"], str):
            clean.append({"type": kind, "data": dict(data)})
        elif kind == "image" and isinstance(data, dict) and set(data) == {"file"} and isinstance(data["file"], str) and data["file"].startswith("base64://"):
            try:
                raw = base64.b64decode(data["file"][9:], validate=True)
            except (ValueError, binascii.Error):
                raise ValueError("invalid_segments") from None
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("invalid_segments")
            clean.append({"type": kind, "data": dict(data)})
        else:
            raise ValueError("invalid_segments")
    return clean


def _prepare(group_id, task_id, actions, context):
    group_id = _group(group_id, context)
    UUID(str(task_id))
    if not isinstance(actions, list):
        raise ValueError("invalid_action")
    result = []
    group_root = (context.settings.data_root / "groups" / group_id).resolve()
    for index, action in enumerate(actions):
        if not isinstance(action, dict) or action.get("type") not in ("send_message", "upload_file"):
            raise ValueError("invalid_action")
        if set(action) - {"type", "text", "path", "name", "segments"}:
            raise ValueError("invalid_action")
        payloads = []
        if action["type"] == "send_message":
            text = action.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("invalid_text")
            if "segments" in action:
                payloads = [{"text": text, "segments": _segments(action["segments"])}]
            else:
                payloads = [{"text": chunk} for chunk in split_text(text, context.settings.max_message_length)]
        else:
            path = Path(action.get("path", ""))
            name = action.get("name", path.name)
            if not isinstance(name, str) or not name or any(ord(c) < 32 or c in "/\\" for c in name) or name in (".", ".."):
                raise ValueError("file_snapshot_invalid")
            if not path.is_absolute() or not path.resolve().is_relative_to(group_root) or not path.is_file():
                raise ValueError("file_snapshot_invalid")
            directory = group_root / "outgoing" / str(task_id) / str(index)
            directory.mkdir(parents=True, exist_ok=True)
            snapshot = directory / name
            before = _hash(path)
            temporary = directory / (name + ".partial")
            shutil.copyfile(path, temporary)
            if _hash(temporary) != before or _hash(path) != before:
                temporary.unlink(missing_ok=True)
                raise ValueError("file_snapshot_invalid")
            os.replace(temporary, snapshot)
            payloads = [{"snapshot_path": str(snapshot), "sha256": before, "byte_size": snapshot.stat().st_size, "name": name}]
        for part, payload in enumerate(payloads):
            result.append({"action_id": f"{task_id}:{index}:{part}", "type": action["type"], "payload": payload, "status": "pending", "attempt": 0, "receipt": None, "error": None, "attempt_history": []})
    return result


async def prepare_actions(group_id, task_id, actions, *, context):
    return await asyncio.to_thread(_prepare, group_id, task_id, actions, context)


def confirmed(kind, response):
    if response.get('retcode') != 0 or response.get('status') != 'ok':
        return False
    data = response.get('data')
    return (kind == 'upload_file' and (data is None or isinstance(data, dict))) or (kind == 'send_message' and isinstance(data, dict) and isinstance(data.get('message_id'), (str, int)) and not isinstance(data.get('message_id'), bool) and str(data['message_id']) != '')


async def run(group_id, task_id, action, *, context):
    result = {"action_id": action.get("action_id"), "status": "failed", "receipt": None, "error": None}
    try:
        group_id = _group(group_id, context)
        if action.get("status") != "sending" or not str(action.get("action_id", "")).startswith(str(task_id) + ":"):
            raise ValueError("invalid_action")
        payload = action["payload"]
        if action["type"] == "send_message":
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("invalid_text")
            api = "send_group_msg"
            message = _segments(payload["segments"]) if "segments" in payload else [{"type": "text", "data": {"text": text}}]
            params = {"group_id": int(group_id), "message": message}
        elif action["type"] == "upload_file":
            path = Path(payload["snapshot_path"]).resolve()
            group_root = (context.settings.data_root / "groups" / group_id / "outgoing" / str(task_id)).resolve()
            if not path.is_relative_to(group_root) or not path.is_file() or await asyncio.to_thread(_hash, path) != payload["sha256"]:
                raise ValueError("file_snapshot_invalid")
            mount = context.settings.napcat_upload_root
            if mount is None:
                raise ValueError("upload_path_unavailable")
            remote_path = mount / path.relative_to(context.settings.data_root.resolve())
            api = "upload_group_file"
            params = {"group_id": int(group_id), "file": str(remote_path), "name": payload["name"]}
        else:
            raise ValueError("invalid_action")
        response = await context.onebot.call(api, params, echo=action.get("echo"))
        if confirmed(action['type'], response):
            result.update(status="sent", receipt=response.get("data") or {})
        elif response.get("status") == "failed" and response.get("retcode") in (1400, 1401, 1403, 1404):
            result["error"] = {"code": "rejected", "message": "OneBot explicitly rejected the request", "safe_to_retry": False}
        else:
            result.update(status="unknown", error={"code": "delivery_unknown", "message": "completion not confirmed", "safe_to_retry": False})
    except NotConnected:
        result["error"] = {"code": "not_connected", "message": "OneBot disconnected before dispatch", "safe_to_retry": True}
    except DeliveryUnknown:
        result.update(status="unknown", error={"code": "delivery_unknown", "message": "request may have been delivered", "safe_to_retry": False})
    except (ValueError, KeyError, TypeError, OSError) as exc:
        code = str(exc) if isinstance(exc, ValueError) else "invalid_action"
        result["error"] = {"code": code, "message": "action validation failed", "safe_to_retry": False}
    return result
