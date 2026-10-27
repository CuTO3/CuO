from __future__ import annotations

import json
import regex as re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

PROMPT_VERSION = "cuo-persona-v1"
MAX_HISTORY_MESSAGES = 40
MAX_HISTORY_CHARS = 16000
MAX_REPLY_CHARS = 6000
RECENT_CONVERSATION_LIMIT = 10
MAX_USER_CONTENT_CHARS = 16500
NICKNAME_DEFAULT_GRAPHEME_LIMIT = 4


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _load_persona(settings: Any) -> str:
    path: Path = Path(__file__).parent / "prompts" / "persona.md"
    fallback = "你是氧化铜（CuO），一只蓝色鲸鱼娘。像熟悉的网友一样简短、自然地聊天。"
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text or fallback
    except OSError:
        return fallback


def _first_n_graphemes(text: str, n: int) -> str:
    if n <= 0:
        return ""
    return "".join(re.findall(r"\X", text)[:n])


def _member_display_name(member: dict) -> str:
    return str(member.get("display_name") or "").strip()


def _member_nickname(member: dict) -> str:
    return str(member.get("nickname") or "").strip()


def _unique_name(base: str, used: set[str]) -> str:
    if base not in used:
        used.add(base)
        return base
    index = 2
    candidate = f"{base}{index}"
    while candidate in used:
        index += 1
        candidate = f"{base}{index}"
    used.add(candidate)
    return candidate


def _resolve_names(members: list[dict]) -> dict[str, str]:
    names: dict[str, str] = {}
    used: set[str] = set()
    for m in sorted(members, key=lambda item: str(item.get("user_id", ""))):
        uid = str(m.get("user_id") or "")
        if not uid:
            continue
        display = _member_display_name(m)
        if display:
            name = _unique_name(display, used)
        else:
            nickname = _member_nickname(m)
            if nickname:
                name = _unique_name(
                    _first_n_graphemes(nickname, NICKNAME_DEFAULT_GRAPHEME_LIMIT),
                    used,
                )
            else:
                continue
        names[uid] = name
    return names


def _original_request_text(log: dict) -> str:
    return str(log.get("original_text") or "").strip()


def _guard_original_request(original_text: str) -> str | None:
    prefix = "<当前用户消息>"
    suffix = "</当前用户消息>"
    overhead = len(prefix) + len(suffix)
    max_request = MAX_USER_CONTENT_CHARS - overhead
    if max_request <= 0 or len(original_text) > max_request:
        return "invalid_request"
    return None


def _make_recent_history_entry(
    m: dict,
    names: dict[str, str],
) -> str | None:
    text = str(m.get("text") or "").strip()
    if not text:
        return None
    user_id = str(m.get("user_id") or "")
    sent_at = m.get("sent_at")
    time_str = sent_at.isoformat() if isinstance(sent_at, datetime) else str(sent_at)
    who = names.get(user_id, "群友")
    return f"[{time_str}] {who}: {text}"


def _prefixed_block(tag: str, content: str) -> str:
    return f"<{tag}>\n{content}\n</{tag}>"


def _build_user_content(
    *,
    original_text: str,
    history_messages: list[dict],
    names: dict[str, str],
    recent_conversations: list[dict],
) -> tuple[str, str | None]:
    request_error = _guard_original_request(original_text)
    if request_error:
        return "", request_error

    request_prefix = "<当前用户消息>"
    request_suffix = "</当前用户消息>"
    request_block = (
        f"{request_prefix}\n{original_text}\n{request_suffix}"
    )

    remaining_history_budget = MAX_USER_CONTENT_CHARS - len(request_block)

    history_entries: list[str] = []
    used_history = 0
    selected_ids: set[int] = set()

    if remaining_history_budget > 0:
        for idx, m in enumerate(reversed(history_messages)):
            original_index = len(history_messages) - 1 - idx
            entry = _make_recent_history_entry(m, names)
            if entry is None:
                continue
            if used_history + len(entry) > remaining_history_budget:
                break
            used_history += len(entry)
            history_entries.append(entry)
            selected_ids.add(original_index)

        history_entries.reverse()
        ordered_selected_ids = sorted(selected_ids)
        last_index = ordered_selected_ids[-1] if ordered_selected_ids else -1

        older_recent_conversations: list[dict] = []
        for conv in recent_conversations:
            result = conv.get("result") or {}
            if isinstance(result, str):
                continue
            reply = result.get("reply") or ""
            original = conv.get("original_text") or ""
            if reply:
                older_recent_conversations.append(
                    {"original": original, "reply": reply}
                )

        if older_recent_conversations and last_index >= 0:
            saved_entries: list[str] = []
            used_saved = 0
            for conv in older_recent_conversations:
                saved = f"问：{conv['original']}\n答：{conv['reply']}"
                if used_history + used_saved + len(saved) > remaining_history_budget:
                    break
                used_saved += len(saved)
                saved_entries.append(saved)

            if saved_entries:
                history_entries = saved_entries + history_entries
                used_history += used_saved
        elif not history_entries and older_recent_conversations:
            saved_entries: list[str] = []
            used_saved = 0
            for conv in older_recent_conversations:
                saved = f"问：{conv['original']}\n答：{conv['reply']}"
                if used_saved + len(saved) > remaining_history_budget:
                    break
                used_saved += len(saved)
                saved_entries.append(saved)
            if saved_entries:
                for saved in saved_entries:
                    history_entries.append(saved)
                used_history += used_saved

    history_block = ""
    if history_entries:
        history_block = _prefixed_block("近期群聊记录", "\n".join(history_entries))
    else:
        history_block = "<近期群聊记录>（暂无）</近期群聊记录>"

    tail = f"\n\n{request_block}\n\n请以氧化铜的身份回复这条消息。"
    if len(tail) > MAX_USER_CONTENT_CHARS:
        return "", "invalid_request"
    available = MAX_USER_CONTENT_CHARS - len(tail)
    if len(history_block) > available:
        suffix = "（历史已截断）"
        history_block = (history_block[:max(0, available-len(suffix))]+suffix)[:available]
    user_content = history_block + tail
    return user_content, None


def _history_has_text(history_messages: list[dict]) -> bool:
    return any(
        str(m.get("text") or "").strip()
        for m in history_messages
    )


def _build_result(
    status: str,
    *,
    result_id: str | None = None,
    actions: list[dict] | None = None,
    error_code: str | None = None,
    reply: str | None = None,
) -> dict:
    return {
        "status": status,
        "result_id": result_id,
        "actions": actions or [],
        "error_code": error_code,
        "reply": reply,
        "prompt_version": PROMPT_VERSION,
    }


def _limit_utf8_text(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    truncated = encoded[:limit].decode("utf-8", errors="ignore")
    return truncated


def _truncate_reply_utf8(text: str, limit: int) -> str:
    if len(text.encode("utf-8")) <= limit:
        return text
    cut = _limit_utf8_text(text, limit)
    if cut.endswith(("<", "[", "{", "(", "，", "。", "！", "？", " ", "\n")):
        cut = cut.rstrip("<[{( ，。！？ \n")
    return cut


async def run(task: dict, ctx) -> dict:
    group_id = str(task.get("group_id") or "")
    task_id = task.get("task_id")
    params = task.get("params") or {}
    if isinstance(params, str):
        params = json.loads(params or "{}")

    triggered_at = task.get("triggered_at")
    if not isinstance(triggered_at, datetime) or triggered_at.tzinfo is None:
        return _build_result("error", error_code="invalid_task")

    if not group_id or not task_id:
        return _build_result("error", error_code="invalid_task")

    task_id_str = str(task_id)
    registered = ctx.db.check_group(group_id)
    if not registered:
        return _build_result("error", error_code="unknown_group")

    snapshot_seq_raw = params.get("snapshot_seq")
    if type(snapshot_seq_raw) is not int:
        return _build_result("error", error_code="invalid_task")
    if snapshot_seq_raw is None:
        return _build_result("error", error_code="invalid_task")
    try:
        snapshot_seq = int(snapshot_seq_raw)
    except (TypeError, ValueError):
        return _build_result("error", error_code="invalid_task")
    if snapshot_seq < 0:
        return _build_result("error", error_code="invalid_task")

    async with ctx.db.transaction(group_id) as tx:
        logs = await ctx.db.read(
            "log",
            group_id=group_id,
            filters={"task_id": task_id_str},
            transaction=tx,
            limit=1,
        )
        if not logs:
            return _build_result("error", error_code="missing_task")

        existing = logs[0]
        if existing.get("business_status") == "completed" and existing.get("result"):
            return existing["result"]

        original_text = _original_request_text(existing)

        messages = await ctx.db.read(
            "messages",
            group_id=group_id,
            filters={
                "sent_at": {"lt": triggered_at},
                "id": {"lte": snapshot_seq},
            },
            order_by=(("id", "desc"),),
            limit=MAX_HISTORY_MESSAGES,
            transaction=tx,
        )
        messages.reverse()

        recent_logs = await ctx.db.read(
            "log",
            group_id=group_id,
            filters={
                "request_type": "conversation",
                "triggered_at": {"lt": triggered_at},
                "business_status": "completed",
            },
            order_by=(("triggered_at", "desc"),),
            limit=RECENT_CONVERSATION_LIMIT,
            transaction=tx,
        )

        members = await ctx.db.read(
            "members",
            group_id=group_id,
            filters={},
            transaction=tx,
        )

        names = _resolve_names(members)

    user_content, content_error = _build_user_content(
        original_text=original_text,
        history_messages=messages,
        names=names,
        recent_conversations=recent_logs,
    )
    if content_error:
        return _build_result("error", error_code=content_error)

    system_prompt = _load_persona(ctx.settings)

    try:
        reply_raw = await ctx.model.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.7,
            max_tokens=2048,
        )
    except Exception:
        return _build_result("error", error_code="model_failed")

    reply = reply_raw.strip()[:MAX_REPLY_CHARS] if isinstance(reply_raw, str) else ""
    if not reply:
        return _build_result("error", error_code="empty_reply")

    actions = [{"type": "send_message", "text": reply}]
    result_payload = _build_result(
        "ok",
        result_id=task_id_str,
        actions=actions,
        reply=reply,
    )

    async with ctx.db.transaction(group_id) as tx:
        current = await ctx.db.read(
            "log",
            group_id=group_id,
            filters={"task_id": task_id_str},
            transaction=tx,
            limit=1,
        )
        if not current:
            return _build_result("error", error_code="missing_task")
        if current[0].get("business_status") == "completed" and current[0].get("result"):
            return current[0]["result"]

        if existing.get("business_status") == "completed":
            return _build_result("error", error_code="invalid_task")

        await ctx.db.write(
            "log",
            [
                {
                    "task_id": task_id_str,
                    "result": _jsonable(result_payload),
                    "business_status": "completed",
                }
            ],
            group_id=group_id,
            mode="update",
            key_fields=("task_id",),
            transaction=tx,
        )

    return result_payload
