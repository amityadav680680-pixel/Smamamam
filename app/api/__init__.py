from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.config import Settings, get_settings
from app.database import get_session
from app.models import Device, SmsMessage
from app.schemas import (
    DeviceOut,
    HealthResponse,
    SmsIngestRequest,
    SmsListResponse,
    SmsOut,
)
from app.telegram.notify import notify_new_sms

router = APIRouter()


def require_webhook_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    token = x_api_key
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token or token != settings.webhook_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def require_admin_key(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    if not x_admin_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin key",
        )


@router.get("/health", response_model=HealthResponse)
async def health(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    sms_count = await session.scalar(select(func.count()).select_from(SmsMessage)) or 0
    device_count = await session.scalar(select(func.count()).select_from(Device)) or 0
    return HealthResponse(
        status="ok",
        version=__version__,
        sms_count=sms_count,
        device_count=device_count,
    )


@router.post(
    "/webhook/sms",
    response_model=SmsOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_webhook_key)],
)
async def ingest_sms(
    payload: SmsIngestRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SmsOut:
    received_at = payload.received_at or datetime.now(timezone.utc)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    msg = SmsMessage(
        device_id=payload.device_id.strip() or "default",
        sender=payload.sender.strip(),
        body=payload.body,
        received_at=received_at,
    )
    session.add(msg)

    result = await session.execute(
        select(Device).where(Device.device_id == msg.device_id)
    )
    device = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if device is None:
        device = Device(device_id=msg.device_id, label=msg.device_id, last_seen_at=now)
        session.add(device)
    else:
        device.last_seen_at = now

    await session.commit()
    await session.refresh(msg)

    if settings.telegram_push_new_sms and settings.telegram_bot_token:
        await notify_new_sms(msg)

    return SmsOut.model_validate(msg)


@router.get(
    "/api/sms",
    response_model=SmsListResponse,
    dependencies=[Depends(require_admin_key)],
)
async def list_sms(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sender: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Search in body"),
    session: AsyncSession = Depends(get_session),
) -> SmsListResponse:
    stmt = select(SmsMessage)
    count_stmt = select(func.count()).select_from(SmsMessage)

    if sender:
        stmt = stmt.where(SmsMessage.sender == sender)
        count_stmt = count_stmt.where(SmsMessage.sender == sender)
    if device_id:
        stmt = stmt.where(SmsMessage.device_id == device_id)
        count_stmt = count_stmt.where(SmsMessage.device_id == device_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(SmsMessage.body.ilike(like))
        count_stmt = count_stmt.where(SmsMessage.body.ilike(like))

    total = await session.scalar(count_stmt) or 0
    result = await session.execute(
        stmt.order_by(SmsMessage.received_at.desc()).offset(offset).limit(limit)
    )
    items = [SmsOut.model_validate(row) for row in result.scalars().all()]
    return SmsListResponse(total=total, items=items)


@router.get(
    "/api/devices",
    response_model=list[DeviceOut],
    dependencies=[Depends(require_admin_key)],
)
async def list_devices(
    session: AsyncSession = Depends(get_session),
) -> list[DeviceOut]:
    result = await session.execute(select(Device).order_by(Device.last_seen_at.desc()))
    return [DeviceOut.model_validate(d) for d in result.scalars().all()]
