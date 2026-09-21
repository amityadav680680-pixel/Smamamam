"""API tests (no Telegram network calls)."""

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ["WEBHOOK_API_KEY"] = "test-webhook-key"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_ALLOWED_USER_IDS"] = ""
os.environ["TELEGRAM_PUSH_NEW_SMS"] = "false"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/test_sms.db"

Path("data").mkdir(parents=True, exist_ok=True)

from app.config import get_settings
from app.database import init_db, reset_engine
from app.main import create_app


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("WEBHOOK_API_KEY", "test-webhook-key")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_PUSH_NEW_SMS", "false")
    get_settings.cache_clear()
    reset_engine()

    await init_db()
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    reset_engine()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "sms_count" in body


@pytest.mark.asyncio
async def test_webhook_requires_key(client: AsyncClient):
    r = await client.post(
        "/webhook/sms",
        json={"sender": "A", "body": "hi"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_ingest_and_list(client: AsyncClient):
    r = await client.post(
        "/webhook/sms",
        headers={"X-API-Key": "test-webhook-key"},
        json={
            "sender": "+91111",
            "body": "Hello from test",
            "device_id": "phone-1",
            "received_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["sender"] == "+91111"
    assert data["body"] == "Hello from test"
    assert data["device_id"] == "phone-1"

    listed = await client.get(
        "/api/sms",
        headers={"X-Admin-Key": "test-admin-key"},
    )
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["sender"] == "+91111"

    devices = await client.get(
        "/api/devices",
        headers={"X-Admin-Key": "test-admin-key"},
    )
    assert devices.status_code == 200
    assert any(d["device_id"] == "phone-1" for d in devices.json())


@pytest.mark.asyncio
async def test_bearer_auth(client: AsyncClient):
    r = await client.post(
        "/webhook/sms",
        headers={"Authorization": "Bearer test-webhook-key"},
        json={"sender": "Bank", "body": "OTP 123456", "device_id": "phone-2"},
    )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_register_device_shows_in_list(client: AsyncClient):
    # Admin: manually put device in DB
    r = await client.post(
        "/api/devices",
        headers={"X-Admin-Key": "test-admin-key"},
        json={"device_id": "my-pixel", "label": "Papa Phone"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["device_id"] == "my-pixel"
    assert body["label"] == "Papa Phone"

    listed = await client.get(
        "/api/devices",
        headers={"X-Admin-Key": "test-admin-key"},
    )
    assert listed.status_code == 200
    devices = listed.json()
    assert any(d["device_id"] == "my-pixel" and d["label"] == "Papa Phone" for d in devices)

    # Webhook path (phone self-register)
    r2 = await client.post(
        "/webhook/device",
        headers={"X-API-Key": "test-webhook-key"},
        json={"device_id": "work-phone", "label": "Office"},
    )
    assert r2.status_code == 201
    listed2 = await client.get(
        "/api/devices",
        headers={"X-Admin-Key": "test-admin-key"},
    )
    ids = {d["device_id"] for d in listed2.json()}
    assert "my-pixel" in ids and "work-phone" in ids

    one = await client.get(
        "/api/devices/my-pixel",
        headers={"X-Admin-Key": "test-admin-key"},
    )
    assert one.status_code == 200
    assert one.json()["device_id"] == "my-pixel"
    assert one.json()["label"] == "Papa Phone"

    missing = await client.get(
        "/api/devices/nope",
        headers={"X-Admin-Key": "test-admin-key"},
    )
    assert missing.status_code == 404
