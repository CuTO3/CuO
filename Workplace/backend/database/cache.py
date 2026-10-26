"""Group-scoped, rebuildable caches. PostgreSQL remains the authority."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg import sql
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)
VERSION = 1
FILES = ('messages', 'divined_users', 'keywords')


def json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f'Unsupported JSON value: {type(value).__name__}')


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def dump(value):
    return json.dumps(value, ensure_ascii=False, default=json_default, allow_nan=False)


class CacheManager:
    def __init__(self, settings, db):
        self.settings, self.db = settings, db
        self.root = Path(getattr(settings, 'backend_root', Path(__file__).resolve().parents[1])).resolve()
        self._ready: set[tuple[str, date]] = set()
        self._dates: dict[str, set[date]] = {}
        db.set_cache(self)

    def _validate(self, group_id, business_date):
        group_id = self.db.check_group(group_id)
        if not group_id.isdecimal():
            raise ValueError('Cache group identifiers must be numeric')
        if isinstance(business_date, str):
            business_date = date.fromisoformat(business_date)
        if type(business_date) is not date:
            raise TypeError('business_date must be a date')
        self._dates.setdefault(group_id, set()).add(business_date)
        return group_id, business_date

    def paths(self, group_id, business_date):
        group_id, business_date = self._validate(group_id, business_date)
        day = business_date.isoformat()
        return {
            'messages': self.root / 'Function' / 'summary' / 'cache' / group_id / day / 'messages.jsonl',
            'divined_users': self.root / 'Function' / 'divine' / 'cache' / group_id / day / 'divined_users.json',
            'keywords': self.root / 'Function' / 'divine' / 'cache' / group_id / day / 'keywords.json',
            'manifest': self.root / 'database' / 'cache' / group_id / day / 'manifest.json',
            'current': self.root / 'database' / 'cache' / group_id / 'current.json',
        }

    def known_dates(self, group_id):
        group_id = self.db.check_group(group_id)
        return set(self._dates.get(group_id, ()))

    async def startup(self):
        # Never trust ready files left by a previous process: rebuild today's
        # data and yesterday's data, then lazily rebuild other requested days.
        today = (datetime.now(ZoneInfo('Asia/Shanghai')) - timedelta(hours=4)).date()
        for group_id in self.db.groups:
            await self.refresh_day(group_id, today - timedelta(days=1))
            await self.refresh_day(group_id, today)

    async def _keywords_from_pg(self, group_id, business_date):
        rows = await self.db.read('log', group_id=group_id,
            filters={'request_type': 'initialize_day', 'business_date': business_date, 'business_status': 'completed'},
            order_by=(('created_at', 'desc'),))
        for row in rows:
            keywords = (row.get('result') or {}).get('keywords')
            if isinstance(keywords, dict) and keywords.get('business_date') == business_date.isoformat() and isinstance(keywords.get('items'), list):
                return {**keywords, 'source_dirty': bool((row.get('result') or {}).get('source_dirty'))}
        return {'business_date': business_date.isoformat(), 'source_business_date': (business_date - timedelta(days=1)).isoformat(),
            'source_status': 'not_initialized', 'rule_version': 'uninitialized', 'items': []}

    async def _refresh_day_locked(self, group_id, business_date):
        paths = self.paths(group_id, business_date)
        self._ready.discard((group_id, business_date))
        await asyncio.to_thread(atomic_write, paths['manifest'], dump(self._manifest(business_date, 'dirty')))
        # The shared group lock excludes writes between the snapshot and ready
        # switch. This does not infer completeness from MAX(id) or commit order.
        messages = await self.db.read('messages', group_id=group_id, filters={'business_date': business_date},
            order_by=(('sent_at', 'asc'), ('id', 'asc')))
        divinations = await self.db.read('divinations', group_id=group_id,
            filters={'business_date': business_date, 'status': 'settled'})
        divined = {row['user_id']: str(row['id']) for row in divinations}
        keywords = await self._keywords_from_pg(group_id, business_date)
        payloads = {'messages': ''.join(dump(row) + '\n' for row in messages), 'divined_users': dump(divined), 'keywords': dump(keywords)}
        for name, text in payloads.items():
            await asyncio.to_thread(atomic_write, paths[name], text)
        manifest = self._manifest(business_date, 'ready')
        manifest.update(message_count=len(messages), divined_count=len(divined))
        await asyncio.to_thread(atomic_write, paths['manifest'], dump(manifest))
        self._ready.add((group_id, business_date))
        return manifest

    def _manifest(self, business_date, state):
        return {'business_date': business_date.isoformat(), 'format_version': VERSION,
            'generated_at': datetime.now(timezone.utc).isoformat(), 'files': {name: state for name in FILES}}

    async def refresh_day(self, group_id, business_date):
        group_id, business_date = self._validate(group_id, business_date)
        async with self.db.group_lock(group_id):
            return await self._refresh_day_locked(group_id, business_date)

    async def _invalidate_locked(self, group_id, business_date, files=FILES):
        if any(name not in FILES for name in files):
            raise ValueError('Unknown cache file')
        self._ready.discard((group_id, business_date))
        manifest = self._manifest(business_date, 'dirty')
        await asyncio.to_thread(atomic_write, self.paths(group_id, business_date)['manifest'], dump(manifest))

    async def invalidate(self, group_id, business_date, files=FILES):
        group_id, business_date = self._validate(group_id, business_date)
        async with self.db.group_lock(group_id):
            await self._invalidate_locked(group_id, business_date, files)

    async def _schedule_repair(self, group_id, business_date, error):
        # Direct pool use avoids recursive cache callbacks while recording a
        # post-commit repair. No business operation is retried or scored again.
        async with self.db._pool.connection() as conn:
            await conn.execute(sql.SQL('''
                INSERT INTO {} (triggered_at,business_date,request_type,params,step,error)
                SELECT CURRENT_TIMESTAMP,%s,'cache_repair',%s,'cache_refresh',%s
                WHERE NOT EXISTS (SELECT FROM {} WHERE request_type='cache_repair'
                    AND business_date=%s AND status IN ('pending','running'))
                ''').format(self.db.table(group_id, 'log'), self.db.table(group_id, 'log')),
                (business_date, Jsonb({'business_date': business_date.isoformat()}),
                 Jsonb({'code': 'cache_write_failed', 'type': type(error).__name__}), business_date))

    async def _after_commit(self, group_id, affected):
        for business_date in sorted(affected):
            try:
                await self._refresh_day_locked(group_id, business_date)
            except Exception as exc:
                logger.exception('Cache refresh failed after committed PostgreSQL write')
                self._ready.discard((group_id, business_date))
                try:
                    await self._invalidate_locked(group_id, business_date)
                except Exception:
                    logger.exception('Unable to persist dirty marker; process memory remains invalid')
                try:
                    await self._schedule_repair(group_id, business_date, exc)
                except Exception:
                    logger.exception('Unable to record cache repair task')

    async def _read(self, name, group_id, business_date):
        group_id, business_date = self._validate(group_id, business_date)
        async with self.db.group_lock(group_id):
            paths = self.paths(group_id, business_date)
            if (group_id, business_date) in self._ready:
                try:
                    manifest = json.loads(await asyncio.to_thread(paths['manifest'].read_text, encoding='utf-8'))
                    if manifest.get('format_version') != VERSION or manifest.get('business_date') != business_date.isoformat() or any(manifest['files'].get(item) != 'ready' for item in FILES):
                        raise ValueError('Cache manifest is invalid')
                    text = await asyncio.to_thread(paths[name].read_text, encoding='utf-8')
                    value = [json.loads(line) for line in text.splitlines() if line] if name == 'messages' else json.loads(text)
                    if name == 'messages':
                        if any(not isinstance(row, dict) or row.get('business_date') != business_date.isoformat() for row in value):
                            raise ValueError('Message cache has an invalid record')
                        if len({row['id'] for row in value}) != len(value):
                            raise ValueError('Message cache has duplicate IDs')
                    elif not isinstance(value, dict):
                        raise ValueError('Invalid cache object')
                    if name == 'keywords' and (value.get('business_date') != business_date.isoformat() or not isinstance(value.get('items'), list)):
                        raise ValueError('Keywords cache has invalid metadata')
                    return value
                except (OSError, ValueError, KeyError, TypeError):
                    self._ready.discard((group_id, business_date))
            try:
                await self._refresh_day_locked(group_id, business_date)
                text = await asyncio.to_thread(paths[name].read_text, encoding='utf-8')
                return [json.loads(line) for line in text.splitlines() if line] if name == 'messages' else json.loads(text)
            except OSError as exc:
                # Cache storage failure is different from missing PostgreSQL
                # records. Return authoritative records directly when possible.
                self._ready.discard((group_id, business_date))
                await self._schedule_repair(group_id, business_date, exc)
                if name == 'messages':
                    rows = await self.db.read('messages', group_id=group_id, filters={'business_date': business_date}, order_by=(('sent_at', 'asc'), ('id', 'asc')))
                    return json.loads(dump(rows))
                if name == 'divined_users':
                    rows = await self.db.read('divinations', group_id=group_id, filters={'business_date': business_date, 'status': 'settled'})
                    return {row['user_id']: str(row['id']) for row in rows}
                return await self._keywords_from_pg(group_id, business_date)

    async def read_messages(self, group_id, business_date):
        return await self._read('messages', group_id, business_date)

    async def read_divined_users(self, group_id, business_date):
        return await self._read('divined_users', group_id, business_date)

    async def read_keywords(self, group_id, business_date):
        return await self._read('keywords', group_id, business_date)

    async def set_current(self, group_id, business_date, task_id):
        group_id, business_date = self._validate(group_id, business_date)
        async with self.db.group_lock(group_id):
            await self._refresh_day_locked(group_id, business_date)
            await asyncio.to_thread(atomic_write, self.paths(group_id, business_date)['current'], dump({
                'business_date': business_date.isoformat(), 'task_id': str(task_id), 'format_version': VERSION}))

    async def prune(self, group_id, business_date):
        """Delete only named, rebuildable files on old days without live tasks."""
        group_id, business_date = self._validate(group_id, business_date)
        cutoff = business_date - timedelta(days=1)
        base = self.root / 'database' / 'cache' / group_id
        if not base.exists():
            return
        async with self.db.group_lock(group_id):
            for directory in base.iterdir():
                if not directory.is_dir() or directory.is_symlink():
                    continue
                try:
                    old_day = date.fromisoformat(directory.name)
                except ValueError:
                    continue
                if old_day >= cutoff:
                    continue
                tasks = await self.db.read('log', group_id=group_id,
                    filters={'business_date': old_day, 'status': {'in': ['pending', 'running', 'failed', 'needs_review']}}, limit=1)
                if tasks:
                    continue
                # Only ready manifests prove this is one of our rebuilt PG copies.
                try:
                    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
                    if manifest.get('format_version') != VERSION or manifest.get('business_date') != old_day.isoformat():
                        continue
                except (OSError, ValueError):
                    continue
                for name, path in self.paths(group_id, old_day).items():
                    if name == 'current' or path.is_symlink():
                        continue
                    if path.exists():
                        path.unlink()
                    try:
                        path.parent.rmdir()
                    except OSError:
                        pass
                self._ready.discard((group_id, old_day))
