from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.db.models import AuditEvent
from libs.db.session import get_db

router = APIRouter()


@router.get("/audit-events")
async def get_audit_events(
    limit: int = Query(100, ge=1, le=500),
    event_type: Optional[str] = None,
    source: Optional[str] = None,
    market: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditEvent)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if source:
        stmt = stmt.where(AuditEvent.source == source)
    if market:
        stmt = stmt.where(AuditEvent.market == market.upper())
    stmt = stmt.order_by(AuditEvent.created_at.desc()).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": row.id,
            "eventType": row.event_type,
            "source": row.source,
            "level": row.level,
            "market": row.market,
            "message": row.message,
            "payload": json.loads(row.payload_json) if row.payload_json else None,
            "ts": row.created_at.isoformat(),
        }
        for row in rows
    ]
