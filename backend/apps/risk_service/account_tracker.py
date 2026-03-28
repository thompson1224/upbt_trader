"""계좌 상태 추적 - 일일 P&L, 연속 손실, 포지션 수 추적."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional


class AccountStateTracker:
    def __init__(self):
        self.daily_pnl: float = 0.0
        self.consecutive_losses: int = 0
        self.loss_streak_date: Optional[str] = None
        self.open_positions_count: int = 0
        self.total_equity: float = 0.0
        self.available_krw: float = 0.0
        self.positions_value: float = 0.0

    def record_trade(self, pnl: float):
        """트레이드 결과 기록."""
        current_date = _risk_metric_date()

        if self.loss_streak_date != current_date:
            self.consecutive_losses = 0
            self.loss_streak_date = current_date

        self.daily_pnl += pnl

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def sync_from_exchange(self, balances: list[dict]):
        """거래소 잔고에서 계좌 상태 동기화."""
        available_krw = 0.0
        positions_value = 0.0
        open_count = 0

        for item in balances:
            currency = str(item.get("currency", "")).upper()
            balance = float(item.get("balance", 0) or 0)
            locked = float(item.get("locked", 0) or 0)
            total_qty = balance + locked

            if currency == "KRW":
                available_krw = balance
                continue

            if total_qty > 0:
                avg_price = float(item.get("avg_buy_price", 0) or 0)
                positions_value += total_qty * avg_price
                open_count += 1

        self.available_krw = available_krw
        self.positions_value = positions_value
        self.total_equity = available_krw + positions_value
        self.open_positions_count = open_count

    def get_account_state(self) -> dict:
        """현재 계좌 상태 반환."""
        return {
            "total_equity": self.total_equity,
            "available_krw": self.available_krw,
            "positions_value": self.positions_value,
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses,
            "open_positions_count": self.open_positions_count,
            "daily_loss_pct": abs(self.daily_pnl) / max(self.total_equity, 1),
            "loss_streak_date": self.loss_streak_date,
        }

    def reset_if_new_day(self):
        """한국 시간 자정이면 상태 초기화."""
        current_date = _risk_metric_date()
        if self.loss_streak_date and self.loss_streak_date != current_date:
            self.daily_pnl = 0.0
            self.consecutive_losses = 0
            self.loss_streak_date = current_date


def _risk_metric_date(now: datetime | None = None) -> str:
    kst = ZoneInfo("Asia/Seoul")
    ts = now.astimezone(kst) if now else datetime.now(tz=kst)
    return ts.strftime("%Y%m%d")
