"""Console access control, persistent settings and optimistic concurrency."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from Integration.console.routes import install, ConsoleSettings
from Integration.console.admin import install as install_admin

HEADERS = {"X-Cuo-Request": "console"}


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    settings = SimpleNamespace(admin_token="test-admin-secret", data_root=tmp_path,
        model_name="deepseek-flash", model_timeout=60.0, max_message_length=1500,
        onebot_timeout=20.0, model_protocol="openai", vision_model_name="",
        vision_api_key="", self_id="12345")
    app.state.ctx = SimpleNamespace(settings=settings, model=SimpleNamespace(client=SimpleNamespace(timeout=None)),
        onebot=SimpleNamespace(timeout=20), db=SimpleNamespace(groups={"123"}), corpus_conflict=False)
    install(app)
    install_admin(app)
    with TestClient(app) as value:
        yield value


def login(client):
    return client.post("/console/api/login", headers=HEADERS, json={"token": "test-admin-secret"})


def test_static_and_protected_routes(client):
    response = client.get("/console/")
    assert response.status_code == 200
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.get("/console/api/settings", headers=HEADERS).status_code == 401
    assert client.get("/admin/groups", headers=HEADERS).status_code == 401
    assert client.post("/console/api/login", json={"token": "test-admin-secret"}).status_code == 403
    assert client.post("/console/api/login", headers=HEADERS, json={"token": "wrong"}).status_code == 401
    response = login(client)
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert client.get("/console/api/settings").status_code == 401
    assert client.get("/admin/groups", headers=HEADERS).json()["groups"] == ["123"]
    assert client.post("/console/api/logout", headers=HEADERS).status_code == 200
    assert client.get("/admin/groups", headers=HEADERS).status_code == 401


def test_settings_validation_persistence_and_conflict(client):
    login(client)
    initial = client.get("/console/api/settings", headers=HEADERS).json()
    assert "test-admin-secret" not in str(initial)
    invalid = {**initial["values"], "model_timeout": 0}
    assert client.put("/console/api/settings", headers=HEADERS, json={"values": invalid, "version": initial["version"]}).status_code == 422
    values = {**initial["values"], "model_timeout": 90.0, "max_message_length": 1200}
    response = client.put("/console/api/settings", headers=HEADERS, json={"values": values, "version": initial["version"]})
    assert response.status_code == 200
    ctx = client.app.state.ctx
    assert ctx.settings.model_timeout == 90
    assert ctx.model.client.timeout.read == 90
    stored = ConsoleSettings.model_validate_json((ctx.settings.data_root / "console-settings.json").read_text())
    assert stored.max_message_length == 1200
    assert client.put("/console/api/settings", headers=HEADERS, json={"values": values, "version": initial["version"]}).status_code == 409
    assert client.put("/console/api/settings", headers=HEADERS, json={"values": {**values,"admin_token":"injected"}, "version":response.json()["version"]}).status_code == 422


def test_rate_limit_and_expired_session(client):
    login(client)
    for token in client.app.state.console_sessions:
        client.app.state.console_sessions[token] = 0
    assert client.get("/console/api/settings", headers=HEADERS).status_code == 401
    for _ in range(9):
        client.post("/console/api/login", headers=HEADERS, json={"token": "bad"})
    assert login(client).status_code == 429


def test_bearer_api_compatibility(client):
    assert client.get("/admin/groups", headers={"Authorization":"Bearer test-admin-secret"}).status_code == 200


def fortune_command(**changes):
    return {"operation":"fortune", "user_id":"456", "fortune":12, "expected_version":"member-version", **changes}


def test_fortune_command_auth_and_enqueue(client):
    from unittest.mock import AsyncMock, Mock
    ctx=client.app.state.ctx
    ctx.db.write=AsyncMock()
    ctx.queue=SimpleNamespace(wake=Mock())
    assert client.post('/admin/123/commands',headers=HEADERS,json=fortune_command()).status_code==401
    login(client)
    assert client.post('/admin/123/commands',json=fortune_command()).status_code==401
    assert client.post('/admin/999/commands',headers=HEADERS,json=fortune_command()).status_code==404
    ctx.db.write.assert_not_awaited()
    response=client.post('/admin/123/commands',headers=HEADERS,json=fortune_command())
    assert response.status_code==202
    args=ctx.db.write.call_args
    assert args.args[0]=='log' and args.kwargs['group_id']=='123'
    entry=args.args[1][0]
    assert entry['params']==fortune_command() and entry['task_id']==response.json()['task_id']
    assert entry['request_type']=='admin_update'
    ctx.queue.wake.assert_called_once()


@pytest.mark.parametrize('changes',[
    {'fortune':True},{'fortune':1.5},{'fortune':'5'},{'fortune':None},
    {'fortune':9007199254740992},{'fortune':-9007199254740992},
    {'user_id':''},{'user_id':'abc'},{'user_id':'１２３'},
    {'expected_version':None},{'admin_token':'injected'},
])
def test_fortune_rejects_invalid_values_without_queue_write(client,changes):
    from unittest.mock import AsyncMock
    client.app.state.ctx.db.write=AsyncMock()
    login(client)
    assert client.post('/admin/123/commands',headers=HEADERS,json=fortune_command(**changes)).status_code==422
    client.app.state.ctx.db.write.assert_not_awaited()


def test_command_status_auth_and_group_scope(client):
    from unittest.mock import AsyncMock
    from uuid import uuid4
    tid=str(uuid4())
    record={'task_id':tid,'request_type':'admin_update','status':'completed','result':{'fortune_after':12}}
    ctx=client.app.state.ctx
    ctx.db.read=AsyncMock(return_value=[record])
    path='/admin/123/commands/'+tid
    assert client.get(path,headers=HEADERS).status_code==401
    login(client)
    assert client.get('/admin/999/commands/'+tid,headers=HEADERS).status_code==404
    assert client.get('/admin/123/commands/invalid',headers=HEADERS).status_code==422
    response=client.get(path,headers=HEADERS)
    assert response.status_code==200 and response.json()['record']==record
    ctx.db.read.assert_awaited_once_with('log',group_id='123',filters={'task_id':tid,'request_type':'admin_update'},limit=1)
    ctx.db.read.return_value=[]
    assert client.get(path,headers=HEADERS).status_code==404
