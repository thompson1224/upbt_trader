from __future__ import annotations

import json
import logging
from typing import Any

from libs.db.models import AuditEvent
from libs.db.session import get_session_factory

logger = logging.getLogger(__name__)


async def record_audit_event(
    *,
    event_type: str,
    source: str,
    message: str,
    level: str = "info",
    market: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    session_factory = get_session_factory()
    try:
        async with session_factory() as db:
            db.add(
                AuditEvent(
                    event_type=event_type,
                    source=source,
                    level=level,
                    market=market,
                    message=message[:255],
                    payload_json=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                )
            )
            await db.commit()
    except Exception as e:
        logger.warning("Failed to record audit event %s/%s: %s", source, event_type, e)
