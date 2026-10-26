"""Typed, allowlisted PostgreSQL access. SQL identifiers never come from messages."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

# kind, nullable. Missing required fields are checked by PostgreSQL, while all
# supplied fields and every record are validated before a connection is acquired.
FIELDS = {
    'log': dict(task_id=('uuid', False), created_at=('time', False), triggered_at=('time', False), business_date=('date', False), request_type=('text', False), user_id=('text', True), message_id=('text', True), original_text=('text', True), params=('json', False), status=('text', False), business_status=('text', False), step=('text', False), result=('json', False), error=('json', True), completed_at=('time', True)),
    'messages': dict(id=('int', False), message_id=('text', False), sent_at=('time', False), received_at=('time', False), business_date=('date', False), user_id=('text', False), nickname=('text', False), text=('text', False), segments=('json', False), generated_by=('text', True), processing=('json', False)),
    'members': dict(user_id=('text', False), nickname=('text', False), display_name=('text', True), slots=('json', False), sheet_name=('text', True), fortune=('int', False), updated_at=('time', False)),
    'summaries': dict(id=('uuid', False), task_id=('uuid', False), business_date=('date', False), start_at=('time', False), end_at=('time', False), content=('text', False), created_at=('time', False)),
    'divinations': dict(id=('uuid', False), task_id=('uuid', False), user_id=('text', False), business_date=('date', False), status=('text', False), zhou_yi=('json', True), tarot=('json', True), dictum=('json', True), keyword=('text', True), advice=('text', True), luck_delta=('int', True), fortune_before=('int', True), fortune_after=('int', True), content=('text', True), created_at=('time', False), settled_at=('time', True)),
}
UNIQUE_KEYS = {
    'log': (frozenset({'task_id'}),),
    'messages': (frozenset({'id'}), frozenset({'message_id'})),
    'members': (frozenset({'user_id'}),),
    'summaries': (frozenset({'id'}), frozenset({'task_id'})),
    'divinations': (frozenset({'id'}), frozenset({'task_id'}), frozenset({'user_id', 'business_date'})),
}
STATES = {('log', 'status'): {'pending', 'running', 'completed', 'failed', 'needs_review'}, ('log', 'business_status'): {'pending', 'running', 'completed', 'failed'}, ('divinations', 'status'): {'generating', 'settled', 'failed'}}


def _value(table: str, field: str, value: Any, *, filter_value: bool = False):
    if field not in FIELDS[table]:
        raise ValueError(f'Unknown {table} field: {field}')
    kind, nullable = FIELDS[table][field]
    if value is None:
        if not nullable and not filter_value:
            raise TypeError(f'{table}.{field} cannot be null')
        return None
    try:
        if kind == 'text':
            if not isinstance(value, str):
                raise TypeError('expected text')
        elif kind == 'int':
            if type(value) is not int:
                raise TypeError('expected integer')
        elif kind == 'uuid':
            value = value if isinstance(value, UUID) else UUID(value)
        elif kind == 'date':
            if isinstance(value, str):
                value = date.fromisoformat(value)
            if type(value) is not date:
                raise TypeError('expected date without time')
        elif kind == 'time':
            if isinstance(value, str):
                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise TypeError('expected timezone-aware datetime')
        elif kind == 'json':
            json.dumps(value, allow_nan=False)
            if field == 'slots' and (not isinstance(value, list) or len(value) != 6 or any(item is not None and not isinstance(item, str) for item in value)):
                raise ValueError('slots must contain six strings/nulls')
            if field == 'segments' and not isinstance(value, list):
                raise TypeError('segments must be an array')
            return Jsonb(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise TypeError(f'Invalid {table}.{field}: expected {kind}') from exc
    allowed = STATES.get((table, field))
    if allowed and value not in allowed:
        raise ValueError(f'Invalid {table}.{field} state')
    if table == 'divinations' and field == 'luck_delta' and not -10 <= value <= 10:
        raise ValueError('luck_delta must be between -10 and 10')
    return value


class Database:
    def __init__(self, settings):
        self.settings = settings
        self.groups = frozenset(str(key) for key in settings.groups)
        if not self.groups:
            raise ValueError('At least one registered group is required')
        self.schemas = {}
        for group_id in self.groups:
            configured = settings.groups[group_id]
            schema = configured.get('schema', group_id) if isinstance(configured, dict) else getattr(configured, 'schema', group_id)
            if not group_id.isdecimal() or not str(schema).isdecimal():
                raise ValueError('Registered groups and schemas must be decimal identifiers')
            self.schemas[group_id] = str(schema)
        self._pool = AsyncConnectionPool(settings.database_url, open=False, min_size=getattr(settings, 'database_pool_min', 1),
            max_size=getattr(settings, 'database_pool_max', 8), kwargs={'row_factory': dict_row})
        self._locks = {group: asyncio.Lock() for group in self.groups}
        self._transactions: dict[int, tuple[str, set[date]]] = {}
        self._cache = None

    def check_group(self, group_id: str) -> str:
        group_id = str(group_id)
        if group_id not in self.groups:
            raise ValueError('Group is not registered')
        return group_id

    def group_lock(self, group_id: str):
        return self._locks[self.check_group(group_id)]

    def table(self, group_id: str, table: str):
        group_id = self.check_group(group_id)
        if table not in FIELDS:
            raise ValueError(f'Table is not allowlisted: {table}')
        return sql.Identifier(self.schemas[group_id], table)

    def set_cache(self, cache):
        self._cache = cache

    async def open(self):
        await self._pool.open(wait=True)

    async def close(self):
        await self._pool.close()

    @asynccontextmanager
    async def transaction(self, group_id: str):
        group_id = self.check_group(group_id)
        async with self.group_lock(group_id):
            affected: set[date] = set()
            async with self._pool.connection() as conn:
                self._transactions[id(conn)] = (group_id, affected)
                try:
                    async with conn.transaction():
                        yield conn
                finally:
                    self._transactions.pop(id(conn), None)
            # Release the connection before rebuilding (also works with a
            # one-connection pool). Keep the group lock until the cache switch.
            if self._cache is not None and affected:
                try:
                    await self._cache._after_commit(group_id, affected)
                except Exception:
                    logger.exception('Committed transaction cache repair failed')

    def _check_transaction(self, group_id, transaction):
        managed = self._transactions.get(id(transaction))
        if managed is None or managed[0] != group_id:
            raise ValueError('Transaction must be created by this database for the same group')

    def _touch(self, conn, rows):
        tracked = self._transactions.get(id(conn))
        if tracked:
            tracked[1].update(row['business_date'] for row in rows if isinstance(row.get('business_date'), date))

    async def fetch(self, group_id, query, params=(), transaction=None) -> list[dict]:
        group_id = self.check_group(group_id)
        if transaction is not None:
            self._check_transaction(group_id, transaction)
            cursor = await transaction.execute(query, params)
            rows = await cursor.fetchall() if cursor.description else []
            if cursor.statusmessage and not cursor.statusmessage.startswith(('SELECT', 'SHOW')):
                self._touch(transaction, rows)
            return rows
        async with self.transaction(group_id) as conn:
            return await self.fetch(group_id, query, params, transaction=conn)

    async def execute(self, group_id, query, params=(), transaction=None) -> int:
        group_id = self.check_group(group_id)
        if transaction is None:
            async with self.transaction(group_id) as conn:
                return await self.execute(group_id, query, params, transaction=conn)
        self._check_transaction(group_id, transaction)
        cursor = await transaction.execute(query, params)
        if self._cache is not None and cursor.rowcount > 0:
            self._transactions[id(transaction)][1].update(self._cache.known_dates(group_id))
        return cursor.rowcount

    def _filters(self, table, filters):
        if not isinstance(filters, dict):
            raise TypeError('filters must be a dictionary')
        clauses, params = [], []
        comparisons = {'eq': '=', 'gte': '>=', 'gt': '>', 'lte': '<=', 'lt': '<'}
        for field, value in filters.items():
            if field not in FIELDS[table]:
                raise ValueError(f'Unknown {table} field: {field}')
            explicit_ops = isinstance(value, dict) and bool(value) and set(value).issubset({'eq', 'gte', 'gt', 'lte', 'lt', 'in'})
            operations = value if isinstance(value, dict) and (FIELDS[table][field][0] != 'json' or explicit_ops) else {'eq': value}
            if not operations:
                raise ValueError('Filter conditions cannot be empty')
            for op, operand in operations.items():
                identifier = sql.Identifier(field)
                if op == 'in':
                    if not isinstance(operand, (list, tuple)):
                        raise TypeError('in requires a list/tuple')
                    if not operand:
                        clauses.append(sql.SQL('FALSE'))
                        continue
                    values = [_value(table, field, item, filter_value=True) for item in operand]
                    nonnull = [item for item in values if item is not None]
                    parts = []
                    if nonnull:
                        parts.append(sql.SQL('{} IN ({})').format(identifier, sql.SQL(',').join(sql.Placeholder() for _ in nonnull)))
                        params.extend(nonnull)
                    if len(nonnull) != len(values):
                        parts.append(sql.SQL('{} IS NULL').format(identifier))
                    clauses.append(sql.SQL('({})').format(sql.SQL(' OR ').join(parts)))
                elif op in comparisons:
                    operand = _value(table, field, operand, filter_value=True)
                    if operand is None:
                        if op != 'eq':
                            raise ValueError('Only eq supports null')
                        clauses.append(sql.SQL('{} IS NULL').format(identifier))
                    else:
                        clauses.append(sql.SQL('{} {} %s').format(identifier, sql.SQL(comparisons[op])))
                        params.append(operand)
                else:
                    raise ValueError(f'Unsupported filter operator: {op}')
        return sql.SQL(' AND ').join(clauses) if clauses else sql.SQL('TRUE'), params

    async def read(self, table, *, group_id, filters, order_by=(), limit=None, transaction=None):
        qualified = self.table(group_id, table)
        condition, params = self._filters(table, filters)
        ordering = []
        for item in order_by:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError('order_by items must be (field, asc/desc) pairs')
            field, direction = item
            if field not in FIELDS[table] or not isinstance(direction, str) or direction.lower() not in ('asc', 'desc'):
                raise ValueError('Invalid order_by')
            ordering.append(sql.SQL('{} {}').format(sql.Identifier(field), sql.SQL(direction.upper())))
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError('limit must be a positive integer or None')
        query = sql.SQL('SELECT * FROM {} WHERE {}').format(qualified, condition)
        if ordering:
            query += sql.SQL(' ORDER BY ') + sql.SQL(',').join(ordering)
        if limit is not None:
            query += sql.SQL(' LIMIT %s')
            params.append(limit)
        if transaction is not None:
            self._check_transaction(self.check_group(group_id), transaction)
            return await (await transaction.execute(query, params)).fetchall()
        # Reads do not need the group commit/cache switch lock.
        async with self._pool.connection() as conn:
            return await (await conn.execute(query, params)).fetchall()

    async def write(self, table, records, *, group_id, mode='insert', key_fields=(), transaction=None):
        qualified = self.table(group_id, table)
        if mode not in ('insert', 'update', 'upsert'):
            raise ValueError('Unsupported write mode')
        if not isinstance(records, list) or any(not isinstance(record, dict) or not record for record in records):
            raise TypeError('records must be a list of nonempty dictionaries')
        if not isinstance(key_fields, (list, tuple)) or len(set(key_fields)) != len(key_fields) or any(key not in FIELDS[table] for key in key_fields):
            raise ValueError('Invalid key_fields')
        if mode in ('update', 'upsert') and not key_fields:
            raise ValueError('update/upsert require key_fields')
        if mode == 'upsert' and frozenset(key_fields) not in UNIQUE_KEYS[table]:
            raise ValueError('upsert requires an actual unique key')
        if mode == 'upsert' and table == 'divinations':
            raise ValueError('Divinations require explicit draft and settlement transactions')
        if mode == 'upsert' and table == 'members' and any('fortune' in row for row in records):
            raise ValueError('Fortune cannot be upserted; use the settlement transaction')
        normalized = []
        for record in records:
            if mode in ('update', 'upsert') and any(key not in record or record[key] is None for key in key_fields):
                raise ValueError('Every record must contain all non-null key fields')
            normalized.append({key: _value(table, key, value) for key, value in record.items()})
        if not normalized:
            return []
        if transaction is None:
            async with self.transaction(group_id) as conn:
                return await self._write(table, qualified, normalized, mode, key_fields, conn)
        self._check_transaction(self.check_group(group_id), transaction)
        return await self._write(table, qualified, normalized, mode, key_fields, transaction)

    async def _write(self, table, qualified, records, mode, key_fields, conn):
        output = []
        for record in records:
            fields = list(record)
            if mode == 'update':
                changed = [field for field in fields if field not in key_fields]
                condition = sql.SQL(' AND ').join(sql.SQL('{} = %s').format(sql.Identifier(key)) for key in key_fields)
                if changed:
                    query = sql.SQL('UPDATE {} SET {} WHERE {} RETURNING *').format(qualified,
                        sql.SQL(',').join(sql.SQL('{} = %s').format(sql.Identifier(key)) for key in changed), condition)
                    params = [record[key] for key in changed] + [record[key] for key in key_fields]
                else:
                    query = sql.SQL('SELECT * FROM {} WHERE {} FOR UPDATE').format(qualified, condition)
                    params = [record[key] for key in key_fields]
            else:
                query = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(qualified,
                    sql.SQL(',').join(sql.Identifier(field) for field in fields), sql.SQL(',').join(sql.Placeholder() for _ in fields))
                params = [record[key] for key in fields]
                if mode == 'upsert':
                    changed = [field for field in fields if field not in key_fields]
                    # A key-only upsert returns the existing row without losing
                    # any fields. The no-op assignment is limited to a key.
                    updates = changed or [key_fields[0]]
                    query += sql.SQL(' ON CONFLICT ({}) DO UPDATE SET {}').format(
                        sql.SQL(',').join(sql.Identifier(key) for key in key_fields),
                        sql.SQL(',').join(sql.SQL('{} = EXCLUDED.{}').format(sql.Identifier(key), sql.Identifier(key)) for key in updates))
                query += sql.SQL(' RETURNING *')
            rows = await (await conn.execute(query, params)).fetchall()
            if mode == 'update' and not rows:
                raise LookupError(f'{table} update matched no records')
            output.extend(rows)
            if table == 'messages' and mode == 'insert':
                await self._mark_keywords_dirty(conn, rows)
            if table in ('messages', 'divinations') or (table == 'log' and any(row.get('request_type') == 'initialize_day' for row in rows)):
                self._touch(conn, rows)
        return output

    async def _mark_keywords_dirty(self, conn, messages):
        from datetime import timedelta
        group_id, affected = self._transactions[id(conn)]
        for source_date in {row['business_date'] for row in messages}:
            target_date = source_date + timedelta(days=1)
            cursor = await conn.execute(sql.SQL('''UPDATE {} SET result = jsonb_set(result,'{{source_dirty}}','true'::jsonb)
                WHERE request_type='initialize_day' AND business_date=%s AND business_status='completed'
                RETURNING task_id''').format(self.table(group_id, 'log')), (target_date,))
            if await cursor.fetchall():
                affected.add(target_date)
                await conn.execute(sql.SQL('''INSERT INTO {} (triggered_at,business_date,request_type,params,step)
                    SELECT CURRENT_TIMESTAMP,%s,'initialize_day',%s,'pending'
                    WHERE NOT EXISTS (SELECT FROM {} WHERE request_type='initialize_day'
                        AND business_date=%s AND status IN ('pending','running'))''').format(
                            self.table(group_id, 'log'), self.table(group_id, 'log')),
                    (target_date, Jsonb({'business_date': target_date.isoformat(), 'source_changed': True}), target_date))


_database: Database | None = None


def configure(database: Database):
    global _database
    _database = database
    return database


def get_database() -> Database:
    if _database is None:
        raise RuntimeError('Database has not been configured')
    return _database


async def PGsql_read(table, *, group_id, filters, order_by=(), limit=None, transaction=None):
    return await get_database().read(table, group_id=group_id, filters=filters, order_by=order_by, limit=limit, transaction=transaction)


async def PGsql_write(table, records, *, group_id, mode='insert', key_fields=(), transaction=None):
    return await get_database().write(table, records, group_id=group_id, mode=mode, key_fields=key_fields, transaction=transaction)
