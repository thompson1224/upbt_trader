from __future__ import annotations

SIGNAL_REASON_LABELS = {
    "held_position_hold": "보유 포지션 유지 조건이라 관망 중입니다.",
    "held_position_ta_exit": "보유 포지션의 TA 약세가 감지돼 청산 방향으로 전환됐습니다.",
    "held_position_downtrend_exit": "하락 추세와 약한 TA 약세가 겹쳐 보수적으로 청산 방향으로 전환됐습니다.",
    "hold_signal": "전략이 현재 구간을 관망으로 판단했습니다.",
    "fused_sell": "융합 전략이 매도 방향으로 판단했습니다.",
}


def humanize_signal_reason(reason: str | None) -> str | None:
    if not reason:
        return None
    return SIGNAL_REASON_LABELS.get(reason, reason)
