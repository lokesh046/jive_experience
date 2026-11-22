"""Administrator sales reports."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import ReportServiceDep, RequireAdmin
from app.schemas.reports import SalesReport

router = APIRouter(tags=["admin: reports"])


@router.get("/reports/sales", response_model=SalesReport, summary="Sales report")
async def sales_report(
    actor: RequireAdmin,
    service: ReportServiceDep,
    days: Annotated[int, Query(ge=7, le=365, description="Length of the daily chart")] = 30,
    event_id: Annotated[uuid.UUID | None, Query()] = None,
) -> SalesReport:
    """Revenue, tickets, refunds and check-ins per event, plus sales by day.

    With `event_id` the report is for that one event and adds a breakdown by
    ticket category. Money is in paise.
    """
    return await service.sales(days=days, event_id=event_id)
