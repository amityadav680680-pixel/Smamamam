from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SmsIngestRequest(BaseModel):
    sender: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=0, max_length=10000)
    device_id: str = Field(default="default", max_length=128)
    received_at: Optional[datetime] = None


class SmsOut(BaseModel):
    id: int
    device_id: str
    sender: str
    body: str
    received_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class SmsListResponse(BaseModel):
    total: int
    items: list[SmsOut]


class DeviceRegisterRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    label: str = Field(default="", max_length=255)


class DeviceOut(BaseModel):
    device_id: str
    label: str
    last_seen_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str
    version: str
    sms_count: int
    device_count: int
