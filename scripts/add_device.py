#!/usr/bin/env python3
"""Add (or update) a device in the local SQLite DB.

Usage:
  PYTHONPATH=. python scripts/add_device.py my-pixel "Papa Phone"
  PYTHONPATH=. python scripts/add_device.py my-pixel
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure project root is importable when run as a script
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.database import SessionLocal, init_db, reset_engine
from app.models import Device
from datetime import datetime, timezone
from sqlalchemy import select


async def main(device_id: str, label: str) -> None:
    Path("data").mkdir(parents=True, exist_ok=True)
    get_settings.cache_clear()
    reset_engine()
    await init_db()

    async with SessionLocal() as session:
        result = await session.execute(
            select(Device).where(Device.device_id == device_id)
        )
        device = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if device is None:
            device = Device(device_id=device_id, label=label, last_seen_at=now)
            session.add(device)
            action = "created"
        else:
            device.label = label
            device.last_seen_at = now
            action = "updated"
        await session.commit()
        print(f"OK — device {action}: id={device_id!r} label={label!r}")
        print("Telegram: /devices  |  API: GET /api/devices")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    did = sys.argv[1].strip()
    lbl = " ".join(sys.argv[2:]).strip() or did
    asyncio.run(main(did, lbl))
