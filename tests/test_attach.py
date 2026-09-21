"""Attachment + firebase helper tests."""

import os
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

os.environ["WEBHOOK_API_KEY"] = "test-webhook-key"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_ALLOWED_USER_IDS"] = ""
os.environ["TELEGRAM_PUSH_NEW_SMS"] = "false"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/test_attach.db"
os.environ["FIREBASE_RTDB_URL"] = ""

Path("data").mkdir(parents=True, exist_ok=True)

from app.config import get_settings
from app.database import SessionLocal, init_db, reset_engine
from app.firebase_sync import firebase_attach_device
from app.models import Device, UserAttachment
from datetime import datetime, timezone


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    db_path = tmp_path / "attach.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("FIREBASE_RTDB_URL", "")
    get_settings.cache_clear()
    reset_engine()
    await init_db()
    yield
    reset_engine()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_attach_one_device_not_all(db):
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        session.add(Device(device_id="phone-a", label="A", last_seen_at=now))
        session.add(Device(device_id="phone-b", label="B", last_seen_at=now))
        session.add(
            UserAttachment(
                telegram_user_id=111,
                device_id="phone-a",
                attached_at=now,
            )
        )
        await session.commit()

        att = await session.execute(
            select(UserAttachment).where(UserAttachment.telegram_user_id == 111)
        )
        row = att.scalar_one()
        assert row.device_id == "phone-a"

        # Only one attachment row per user
        all_att = await session.execute(select(UserAttachment))
        assert len(list(all_att.scalars().all())) == 1


@pytest.mark.asyncio
async def test_firebase_noop_when_unset(db):
    result = await firebase_attach_device("x", label="X", telegram_user_id=1)
    assert result is None
