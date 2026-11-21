"""System endpoint contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class DependencyStatus(BaseModel):
    database: bool
    redis: bool


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    checked_at: str
    dependencies: DependencyStatus


class ServiceInfo(BaseModel):
    name: str
    version: str
    environment: str
    api_version: str
    default_timezone: str
    currency: str
