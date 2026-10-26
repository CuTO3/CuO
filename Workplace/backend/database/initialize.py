"""04:00 business-day initialization without deleting persistent records."""
from __future__ import annotations

import inspect
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4


def _day(value):
    if isinstance(value, str):
        value = date.fromisoformat(value)
    if type(value) is not date:
        raise TypeError('business_date must be a date')
    return value


async def _extract(messages, context):
    # Reuse the local divine extractor when available; no per-message AI calls.
    from Function.divine.son_function.keywords import extract_candidates
    rules_path = Path(context.settings.backend_root) / 'Function' / 'divine' / 'data' / 'keyword_rules.json'
    rules = json.loads(rules_path.read_text(encoding='utf-8')) if rules_path.exists() else None
    parameters = inspect.signature(extract_candidates).parameters
    kwargs = {}
    if 'rules' in parameters:
        kwargs['rules'] = rules
    result = extract_candidates(messages, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, dict):
        return result.get('items', []), result.get('rule_version', 'local-v1')
    if not isinstance(result, list):
        raise TypeError('Keyword extractor must return a candidate list')
    return result, (rules or {}).get('version', 'local-v1')


async def _ensure_archive(group_id, previous, context):
    db = context.db
    async with db.transaction(group_id) as tx:
        existing = await db.read('log', group_id=group_id,
            filters={'business_date': previous, 'request_type': 'archive_day'}, limit=1, transaction=tx)
        if not existing:
            await db.write('log', [{'task_id': uuid4(), 'triggered_at': datetime.now(timezone.utc),
                'business_date': previous, 'request_type': 'archive_day',
                'params': {'business_date': previous.isoformat()}, 'step': 'pending'}],
                group_id=group_id, transaction=tx)


async def run(*, group_id: str, business_date: date, task_id, context) -> dict:
    business_date = _day(business_date)
    group_id = context.db.check_group(group_id)
    task_id = UUID(str(task_id))
    db, cache = context.db, context.cache
    previous = business_date - timedelta(days=1)
    await _ensure_archive(group_id, previous, context)

    successful = await db.read('log', group_id=group_id,
        filters={'request_type': 'initialize_day', 'business_date': business_date, 'business_status': 'completed'},
        order_by=(('created_at', 'desc'),))
    keywords = None
    for record in successful:
        result = record.get('result') or {}
        candidate = result.get('keywords')
        if isinstance(candidate, dict) and candidate.get('business_date') == business_date.isoformat() and isinstance(candidate.get('items'), list) and not result.get('source_dirty'):
            keywords = candidate
            break

    existing = await db.read('log', group_id=group_id, filters={'task_id': task_id}, limit=1)
    if existing and (existing[0]['request_type'] != 'initialize_day' or existing[0]['business_date'] != business_date):
        raise ValueError('Initialization task identity does not match its date/group')
    if not existing:
        await db.write('log', [{'task_id': task_id, 'triggered_at': datetime.now(timezone.utc),
            'business_date': business_date, 'request_type': 'initialize_day',
            'params': {'business_date': business_date.isoformat()}, 'status': 'running', 'business_status': 'running'}], group_id=group_id)

    if keywords is None:
        try:
            messages = await db.read('messages', group_id=group_id,
                filters={'business_date': previous}, order_by=(('sent_at', 'asc'), ('id', 'asc')))
            if messages:
                items, version = await _extract(messages, context)
                source_status = 'ready'
            else:
                items, version, source_status = [], 'local-v1', 'no_data'
            keywords = {'business_date': business_date.isoformat(), 'source_business_date': previous.isoformat(),
                'rule_version': version, 'generated_at': datetime.now(timezone.utc).isoformat(),
                'source_status': source_status, 'items': items}
        except Exception as exc:
            await db.write('log', [{'task_id': task_id, 'status': 'failed', 'business_status': 'failed', 'step': 'keywords',
                'error': {'code': 'keyword_extraction_failed', 'type': type(exc).__name__}}],
                group_id=group_id, mode='update', key_fields=('task_id',))
            await cache.invalidate(group_id, business_date)
            raise

    async with db.transaction(group_id) as tx:
        row = (await db.read('log', group_id=group_id, filters={'task_id': task_id}, transaction=tx))[0]
        result = dict(row.get('result') or {})
        result.update(keywords=keywords, source_dirty=False, initialization_version=1)
        # Persist the authoritative keyword copy before writing any cache files.
        await db.write('log', [{'task_id': task_id, 'business_status': 'completed', 'step': 'cache', 'result': result, 'error': None}],
            group_id=group_id, mode='update', key_fields=('task_id',), transaction=tx)

    try:
        await cache.set_current(group_id, business_date, task_id)
    except Exception as exc:
        await db.write('log', [{'task_id': task_id, 'status': 'failed', 'step': 'cache',
            'error': {'code': 'initialization_cache_failed', 'type': type(exc).__name__}}],
            group_id=group_id, mode='update', key_fields=('task_id',))
        # The successful PG keyword copy is retained for the recovery attempt.
        raise
    messages = await cache.read_messages(group_id, business_date)
    divined = await cache.read_divined_users(group_id, business_date)
    output = {'business_date': business_date.isoformat(), 'status': 'completed',
        'keyword_count': len(keywords['items']), 'message_count': len(messages), 'divined_count': len(divined)}
    await db.write('log', [{'task_id': task_id, 'status': 'completed', 'business_status': 'completed',
        'step': 'completed', 'completed_at': datetime.now(timezone.utc), 'error': None,
        'result': {**result, 'initialization': output}}], group_id=group_id, mode='update', key_fields=('task_id',))
    await cache.prune(group_id, business_date)
    return output


async def initialize_day(group_id, business_date, task_id, *, context):
    return await run(group_id=group_id, business_date=business_date, task_id=task_id, context=context)
