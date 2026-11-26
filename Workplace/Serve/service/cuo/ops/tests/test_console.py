"""Console access control, persistent settings and optimistic concurrency."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql
import httpx
import pytest

from Integration.console.routes import install, ConsoleSettings
from Integration.console.admin import install as install_admin

HEADERS = {"X-Cuo-Request": "console"}


@pytest.fixture
def client(tmp_path, example_config_root):
    app = FastAPI()
    settings = SimpleNamespace(config_root=tmp_path/"config", admin_token="test-admin-secret", data_root=tmp_path,
        model_name="deepseek-flash", model_timeout=60.0, max_message_length=1500,
        onebot_timeout=20.0, model_protocol="openai", vision_model_name="",
        vision_api_key="", self_id="12345")
    from Core.configuration import APP_ROOT
    import shutil
    shutil.copytree(example_config_root, settings.config_root)
    app.state.ctx = SimpleNamespace(settings=settings, model=SimpleNamespace(client=SimpleNamespace(timeout=None)),
        onebot=SimpleNamespace(timeout=20), db=SimpleNamespace(groups={"123"}), corpus_conflict=False)
    install(app)
    install_admin(app)
    with TestClient(app) as value:
        yield value


def login(client):
    return client.post("/console/api/login", headers=HEADERS, json={"token": "test-admin-secret"})


def test_overview_reports_onebot_rejection_without_credentials():
    from unittest.mock import AsyncMock
    from starlette.websockets import WebSocketDisconnect
    from Integration.napcat.client import OneBotClient
    from Workflow.main import create_app

    app = create_app()
    db = SimpleNamespace(
        groups={"123"}, table=lambda gid, table: sql.Identifier(table),
        fetch=AsyncMock(side_effect=[[{"n": 0}]] * 4 + [[], []]),
    )
    app.state.ctx = SimpleNamespace(
        settings=SimpleNamespace(admin_token="test-admin-secret", napcat_token="test-napcat-secret",
                                 self_id="12345", model_name="test-model"),
        ready=True, onebot=OneBotClient(), db=db,
    )
    app.state.inbound = asyncio.Queue()
    with pytest.raises(WebSocketDisconnect), TestClient(app).websocket_connect(
        "/onebot/ws", headers={"Authorization": "Bearer wrong-token", "X-Self-ID": "12345"},
    ):
        pytest.fail("invalid OneBot token was accepted")
    client = TestClient(app)
    url = "/console/api/overview/123"
    assert client.get(url, headers=HEADERS).status_code == 401
    assert login(client).status_code == 200
    response = client.get(url, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["onebot_issue"]["code"] == "onebot_token_mismatch"
    assert "test-napcat-secret" not in response.text
    assert "wrong-token" not in response.text


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
    url = '/console/api/configuration/sender'
    initial = client.get(url, headers=HEADERS).json()
    assert 'test-admin-secret' not in str(initial)
    assert client.put(url, headers=HEADERS, json={'values': {'sender_message_character_limit': 0}, 'version': initial['version']}).status_code == 422
    response = client.put(url, headers=HEADERS, json={'values': {'sender_message_character_limit': 1200}, 'version': initial['version']})
    assert response.status_code == 200
    assert response.json()['restart_required'] is True
    from Core.configuration import read
    assert read('sender', root=client.app.state.ctx.settings.config_root)['sender_message_character_limit'] == 1200
    assert client.put(url, headers=HEADERS, json={'values': {}, 'version': initial['version']}).status_code == 409
    assert client.put(url, headers=HEADERS, json={'values': {'admin_token': 'injected'}, 'version': response.json()['version']}).status_code == 422
    assert client.put('/console/api/settings', headers=HEADERS, json={}).status_code == 409


def test_module_secret_is_write_only_and_omission_preserves_it(client):
    login(client)
    url='/console/api/configuration/conversation'
    initial=client.get(url,headers=HEADERS).json()
    secret='synthetic-independent-key'
    response=client.put(url,headers=HEADERS,json={'version':initial['version'],'values':{'conversation_reply_ai_api_key':secret}})
    assert response.status_code==200
    assert secret not in response.text
    assert 'conversation_reply_ai_api_key' not in response.json()['values']
    response=client.put(url,headers=HEADERS,json={'version':response.json()['version'],'values':{'conversation_reply_ai_model_name':'synthetic-model'}})
    assert response.status_code==200
    from Core.configuration import read
    assert read('conversation',root=client.app.state.ctx.settings.config_root)['conversation_reply_ai_api_key']==secret
    assert client.get('/console/api/configuration/unregistered',headers=HEADERS).status_code==404


def test_divine_editor_uses_index_schema_and_cross_field_validation(client):
    login(client)
    url='/console/api/configuration/DivineAIConfig'
    response=client.get(url,headers=HEADERS)
    assert response.status_code==200
    initial=response.json()
    assert 'divine_ai_api_key' not in initial['values']
    assert client.put(url,headers=HEADERS,json={'version':initial['version'],'values':{'divine_ai_enabled':True}}).status_code==422
    assert client.put(url,headers=HEADERS,json={'version':initial['version'],'values':{'divine_ai_advice_min_characters':101}}).status_code==422
    response=client.put(url,headers=HEADERS,json={'version':initial['version'],'values':{'divine_ai_request_attempt_limit':3}})
    assert response.status_code==200
    from Core.module_config import DivineAIConfig, load_module_config
    config=load_module_config('src/backend/Function/divine/son_function/AI_divine_config.toml',DivineAIConfig,config_root=client.app.state.ctx.settings.config_root)
    assert config.divine_ai_request_attempt_limit==3


def test_tarot_version_choices_and_persistence(client):
    from Core.module_config import TarotImageConfig, load_module_config

    url = '/console/api/configuration/TarotImageConfig'
    assert client.get(url, headers=HEADERS).status_code == 401
    assert login(client).status_code == 200
    response = client.get(url, headers=HEADERS)
    assert response.status_code == 200
    initial = response.json()
    key = 'divine_tarot_version'
    assert {'Arknight', 'PrismaVisions', 'TrueDark'} <= set(initial['fields'][key]['choices'])
    for invalid in ('../TrueDark', 'MissingDeck'):
        payload = {'version': initial['version'], 'values': {key: invalid}}
        assert client.put(url, headers=HEADERS, json=payload).status_code == 422

    payload = {'version': initial['version'], 'values': {key: 'TrueDark'}}
    response = client.put(url, headers=HEADERS, json=payload)
    assert response.status_code == 200
    assert response.json()['restart_required'] is True
    config = load_module_config(
        'src/backend/Function/divine/son_function/tarot_image_config.toml',
        TarotImageConfig,
        config_root=client.app.state.ctx.settings.config_root,
    )
    assert config.divine_tarot_version == 'TrueDark'


def test_rate_limit_and_expired_session(client):
    login(client)
    for token in client.app.state.console_sessions:
        client.app.state.console_sessions[token] = 0
    assert client.get("/console/api/settings", headers=HEADERS).status_code == 401
    for _ in range(9):
        client.post("/console/api/login", headers=HEADERS, json={"token": "bad"})
    assert login(client).status_code == 429


@pytest.mark.parametrize("returncode, status", [(0, 202), (-15, 202), (1, 503)])
def test_service_restart_systemctl_exit_status(client, monkeypatch, returncode, status):
    from unittest.mock import AsyncMock
    from Integration.console import service

    process = SimpleNamespace(wait=AsyncMock(return_value=returncode), returncode=returncode)
    monkeypatch.setenv("INVOCATION_ID", "test-service")
    monkeypatch.setattr(service.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    login(client)
    assert client.post("/console/api/service/restart", headers=HEADERS).status_code == status


def test_service_restart_requires_session_and_systemd(client, monkeypatch):
    from unittest.mock import AsyncMock
    from Integration.console import service

    command = AsyncMock()
    monkeypatch.setattr(service, 'restart_service', command)
    url = '/console/api/service/restart'
    assert client.post(url, headers=HEADERS).status_code == 401
    login(client)
    assert client.post(url).status_code == 401
    monkeypatch.delenv('INVOCATION_ID', raising=False)
    assert client.post(url, headers=HEADERS).status_code == 409
    command.assert_not_called()
    monkeypatch.setenv('INVOCATION_ID', 'test-service')
    command.side_effect = RuntimeError('permission denied')
    assert client.post(url, headers=HEADERS).status_code == 503
    command.side_effect = None
    assert client.post(url, headers=HEADERS).status_code == 202
    assert client.post(url, headers=HEADERS).status_code == 409
    assert command.await_count == 2


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
