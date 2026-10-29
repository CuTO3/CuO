'''
本文件用途：PostgreSQL pool construction and lifecycle.

配置字段：
database_url                         私有数据库连接信息
'''

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
def create_pool(settings):
    return AsyncConnectionPool(settings.database_url,open=False,min_size=getattr(settings,"database_pool_min",1),max_size=getattr(settings,"database_pool_max",8),kwargs={"row_factory":dict_row})
class ConnectionLifecycle:
    async def open(self):await self._pool.open(wait=True)
    async def close(self):await self._pool.close()
