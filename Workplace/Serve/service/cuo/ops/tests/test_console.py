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
