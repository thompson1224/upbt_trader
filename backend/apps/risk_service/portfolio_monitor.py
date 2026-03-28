"""포트폴리오 위험 모니터링 - 포지션 집중도, correlation 등 모니터링."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from apps.risk_service.account_tracker import AccountStateTracker


@dataclass
class RiskAlert:
    type: str
    severity: str
    market: str | None
    value: float
    threshold: float
    message: str


class PortfolioRiskMonitor:
    def __init__(self):
        self.position_weights: dict[str, float] = {}

    async def evaluate(
        self,
        account_tracker: AccountStateTracker,
        settings: Any,
    ) -> list[dict]:
        """포트폴리오 위험 상태 평가. 알림 목록 반환."""
        alerts: list[dict] = []

        if account_tracker.total_equity <= 0:
            return alerts

        daily_loss_pct = abs(account_tracker.daily_pnl) / account_tracker.total_equity
        if daily_loss_pct >= settings.risk_max_daily_loss_pct:
            alerts.append(
                {
                    "type": "daily_loss_limit",
                    "severity": "critical",
                    "market": None,
                    "value": daily_loss_pct,
                    "threshold": settings.risk_max_daily_loss_pct,
                    "message": f"Daily loss limit reached: {daily_loss_pct:.2%} >= {settings.risk_max_daily_loss_pct:.2%}",
                    "ts": datetime.now(tz=timezone.utc).isoformat(),
                }
            )
        elif daily_loss_pct >= settings.risk_max_daily_loss_pct * 0.8:
            alerts.append(
                {
                    "type": "daily_loss_warning",
                    "severity": "warning",
                    "market": None,
                    "value": daily_loss_pct,
                    "threshold": settings.risk_max_daily_loss_pct * 0.8,
                    "message": f"Daily loss approaching limit: {daily_loss_pct:.2%}",
                    "ts": datetime.now(tz=timezone.utc).isoformat(),
                }
            )

        if account_tracker.consecutive_losses >= 5:
            alerts.append(
                {
                    "type": "consecutive_losses",
                    "severity": "critical",
                    "market": None,
                    "value": account_tracker.consecutive_losses,
                    "threshold": 5,
                    "message": f"Consecutive losses: {account_tracker.consecutive_losses}",
                    "ts": datetime.now(tz=timezone.utc).isoformat(),
                }
            )

        if account_tracker.open_positions_count >= 5:
            alerts.append(
                {
                    "type": "max_positions",
                    "severity": "warning",
                    "market": None,
                    "value": account_tracker.open_positions_count,
                    "threshold": 5,
                    "message": f"Max open positions reached: {account_tracker.open_positions_count}",
                    "ts": datetime.now(tz=timezone.utc).isoformat(),
                }
            )

        if account_tracker.positions_value > 0:
            position_concentration = (
                account_tracker.positions_value / account_tracker.total_equity
            )
            if position_concentration > settings.risk_max_position_pct:
                alerts.append(
                    {
                        "type": "position_concentration",
                        "severity": "warning",
                        "market": None,
                        "value": position_concentration,
                        "threshold": settings.risk_max_position_pct,
                        "message": f"Position concentration high: {position_concentration:.2%}",
                        "ts": datetime.now(tz=timezone.utc).isoformat(),
                    }
                )

        if account_tracker.available_krw < account_tracker.total_equity * 0.1:
            liquidity_ratio = (
                account_tracker.available_krw / account_tracker.total_equity
            )
            if liquidity_ratio < 0.05:
                alerts.append(
                    {
                        "type": "low_liquidity",
                        "severity": "warning",
                        "market": None,
                        "value": liquidity_ratio,
                        "threshold": 0.1,
                        "message": f"Low liquidity: only {liquidity_ratio:.2%} available",
                        "ts": datetime.now(tz=timezone.utc).isoformat(),
                    }
                )

        return alerts
