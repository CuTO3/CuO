import asyncio,os,sys
if sys.platform=="win32":asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from uuid import uuid4
from types import SimpleNamespace
import pytest
import pytest
# 在导入业务模块前建立独立测试配置，仅从公开 example 复制。
import atexit
import tempfile
from pathlib import Path
from ops.configure import initialize
_example_directory = tempfile.TemporaryDirectory(prefix="cuo-example-tests-")
initialize(_example_directory.name)
os.environ["CUO_CONFIG_ROOT"] = _example_directory.name
atexit.register(_example_directory.cleanup)

@pytest.fixture(scope="session")
def example_config_root():
    return Path(_example_directory.name)

from Core.settings import Settings
from Integration.postgresql import Database
from ops.database.scripts.migrate import migrate
from Core.context import RuntimeContext
class FakeModel:
    def __init__(self):self.calls=[];self.reply="收到喵。"
    async def complete(self,**kw):self.calls.append(kw);return self.reply
class FakeBot:
    connected=True
    def __init__(self):self.calls=[];self.fail=None
    async def call(self,action,params,**kw):
        self.calls.append((action,params,kw))
        if self.fail:raise self.fail
        return {"status":"ok","retcode":0,"data":{"message_id":str(90000+len(self.calls))} if action=="send_group_msg" else None}
@pytest.fixture
async def ctx(tmp_path):
    dsn=os.getenv("CUO_TEST_DSN")
    if not dsn:pytest.skip("isolated PostgreSQL required: CUO_TEST_DSN")
    ids=[str(uuid4().int%10**12) for _ in range(2)]
    s=Settings(database_url=dsn,groups={i:{"schema":i} for i in ids},backend_root=tmp_path/"code",data_root=tmp_path/"data",napcat_upload_root=tmp_path/"data",self_id="999",napcat_token="test-only",admin_token="admin-test")
    db=Database(s);await db.open();await migrate(db)
    c=RuntimeContext(s,db,FakeModel(),FakeBot());c.gid=ids[0];c.other=ids[1]
    c.queue=SimpleNamespace(wake=lambda:None)
    try:yield c
    finally:await db.close()
