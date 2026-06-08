"""Pydantic schemas for the billing API."""
from typing import Literal, Optional

from pydantic import BaseModel


class SubscribeRequest(BaseModel):
    plan: Literal["free", "pro", "enterprise"]
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class SubscribeResponse(BaseModel):
    checkout_url: str
    session_id: str


class PortalResponse(BaseModel):
    portal_url: str


class UsageResponse(BaseModel):
    plan: str
    current_period_start: int  # unix timestamp
    current_period_end: int
    usage: dict[str, int]  # metric -> quantity in current period
    caps: dict[str, int]  # metric -> cap for plan


class WebhookAck(BaseModel):
    received: bool
    event_type: Optional[str] = None


class ChangePlanRequest(BaseModel):
    plan: Literal["pro", "enterprise"]
