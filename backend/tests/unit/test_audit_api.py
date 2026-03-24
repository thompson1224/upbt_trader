from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.gateway.api.v1 import audit as audit_module


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _stmt):
        return _FakeResult(self.rows)


@pytest.mark.asyncio
async def test_get_audit_events_returns_serialized_rows():
    rows = [
        SimpleNamespace(
            id=1,
            event_type="order_filled",
            source="execution",
            level="info",
            market="KRW-BTC",
            message="order_filled KRW-BTC",
            payload_json='{"type":"order_filled","market":"KRW-BTC"}',
            created_at=datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc),
        )
    ]

    response = await audit_module.get_audit_events(limit=100, db=_FakeSession(rows))

    assert response == [
        {
            "id": 1,
            "eventType": "order_filled",
            "source": "execution",
            "level": "info",
            "market": "KRW-BTC",
            "message": "order_filled KRW-BTC",
            "payload": {"type": "order_filled", "market": "KRW-BTC"},
            "ts": "2026-03-25T00:00:00+00:00",
        }
    ]
