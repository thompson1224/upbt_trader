from __future__ import annotations
from typing import Optional
"""사전 위험관리 - 주문 실행 전 검증"""
from dataclasses import dataclass
from typing import Literal

from libs.config import get_settings


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    adjusted_qty: Optional[float] = None


@dataclass
class AccountState:
    total_equity: float          # 총 자산 (KRW)
    available_krw: float         # 사용 가능 KRW
    daily_pnl: float             # 오늘 손익 (음수 = 손실)
    consecutive_losses: int      # 연속 손실 횟수
    open_positions_count: int    # 현재 열린 포지션 수
    market_warning: bool         # 시장 경보 여부


class PreTradeRiskGuard:
    """주문 실행 전 위험 검증."""

    MAX_OPEN_POSITIONS = 5
    MAX_CONSECUTIVE_LOSSES = 5

    def __init__(self):
        self.settings = get_settings()

    def evaluate(
        self,
        side: Literal["buy", "sell"],
        market: str,
        suggested_qty: float,
        entry_price: float,
        stop_loss: float | None,
        account: AccountState,
    ) -> RiskDecision:
        """
        매매 신호에 대한 위험 평가.
        Returns RiskDecision(approved=True/False, reason=..., adjusted_qty=...)
        """
        # 1. 시장 경보 코인 거래 금지
        if account.market_warning:
            return RiskDecision(False, f"Market warning active for {market}")

        # 2. 매수 전용 추가 체크
        if side == "buy":
            # 일일 손실 한도는 신규 진입만 차단한다.
            daily_loss_pct = abs(account.daily_pnl) / max(account.total_equity, 1)
            if account.daily_pnl < 0 and daily_loss_pct >= self.settings.risk_max_daily_loss_pct:
                return RiskDecision(
                    False,
                    f"Daily loss limit reached: {daily_loss_pct:.1%} >= {self.settings.risk_max_daily_loss_pct:.1%}",
                )

            # 연속 손실 제한도 신규 진입만 차단한다.
            if account.consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
                return RiskDecision(
                    False,
                    f"Max consecutive losses reached: {account.consecutive_losses}",
                )

            # 최대 동시 포지션 수
            if account.open_positions_count >= self.MAX_OPEN_POSITIONS:
                return RiskDecision(
                    False,
                    f"Max open positions reached: {account.open_positions_count}",
                )

            # 단일 거래 최대 금액
            order_value = suggested_qty * entry_price
            max_single_value = account.total_equity * self.settings.risk_max_single_trade_pct
            if order_value > max_single_value:
                # 수량 축소
                adjusted_qty = max_single_value / entry_price
                return RiskDecision(
                    True,
                    f"Qty adjusted: {suggested_qty:.6f} → {adjusted_qty:.6f}",
                    adjusted_qty=adjusted_qty,
                )

            # 포지션 최대 비중
            position_pct = order_value / max(account.total_equity, 1)
            if position_pct > self.settings.risk_max_position_pct:
                adjusted_qty = (account.total_equity * self.settings.risk_max_position_pct) / entry_price
                return RiskDecision(
                    True,
                    f"Position size capped at {self.settings.risk_max_position_pct:.1%}",
                    adjusted_qty=adjusted_qty,
                )

        return RiskDecision(True, "Approved", adjusted_qty=suggested_qty)


class PositionSizer:
    """포지션 사이징 계산."""

    # 업비트 KRW 최소 주문금액
    MIN_ORDER_KRW = 5_000

    def __init__(self):
        self.settings = get_settings()

    def calculate_qty(
        self,
        equity: float,
        entry_price: float,
        stop_loss: float,
        risk_pct: Optional[float] = None,
    ) -> float:
        """
        손절가 기반 포지션 사이징.
        risk_budget = equity * risk_pct
        qty = risk_budget / |entry - stop_loss|
        """
        if risk_pct is None:
            risk_pct = self.settings.risk_max_single_trade_pct

        risk_budget = equity * risk_pct
        price_risk = abs(entry_price - stop_loss)

        if price_risk < entry_price * 0.001:  # 0.1% 미만 손절폭 방지
            price_risk = entry_price * 0.02  # 기본 2% 손절

        qty = risk_budget / price_risk

        # 최소 주문금액 체크
        if qty * entry_price < self.MIN_ORDER_KRW:
            return 0.0

        return qty
