"""Optional Firebase Realtime Database sync for device attach."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _base_url() -> str:
    settings = get_settings()
    return settings.firebase_rtdb_url.rstrip("/")


def _auth_params() -> dict[str, str]:
    settings = get_settings()
    if settings.firebase_auth_token.strip():
        return {"auth": settings.firebase_auth_token.strip()}
    return {}


async def firebase_attach_device(
    device_id: str,
    *,
    label: str = "",
    telegram_user_id: int | None = None,
) -> dict[str, Any] | None:
    """Write/attach a single device under /config/{device_id} and /devices/{device_id}."""
    settings = get_settings()
    if not settings.firebase_enabled:
        return None

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "device_id": device_id,
        "label": label or device_id,
        "monitoring": True,
        "attached": True,
        "attached_at": now,
        "telegram_user_id": telegram_user_id,
    }

    base = _base_url()
    params = _auth_params()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Active attach pointer (only one current device)
            cur = await client.put(
                f"{base}/attached.json",
                params=params,
                json={
                    "device_id": device_id,
                    "label": label or device_id,
                    "attached_at": now,
                    "telegram_user_id": telegram_user_id,
                },
            )
            cur.raise_for_status()

            cfg = await client.put(
                f"{base}/config/{device_id}.json",
                params=params,
                json=payload,
            )
            cfg.raise_for_status()

            dev = await client.put(
                f"{base}/devices/{device_id}.json",
                params=params,
                json=payload,
            )
            dev.raise_for_status()
        logger.info("Firebase attached device_id=%s", device_id)
        return payload
    except Exception as exc:
        logger.exception("Firebase attach failed for %s: %s", device_id, exc)
        raise


async def firebase_detach() -> None:
    settings = get_settings()
    if not settings.firebase_enabled:
        return
    base = _base_url()
    params = _auth_params()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.put(
                f"{base}/attached.json",
                params=params,
                content="null",
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
    except Exception as exc:
        logger.exception("Firebase detach failed: %s", exc)
        raise
