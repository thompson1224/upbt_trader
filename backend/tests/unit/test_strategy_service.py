from apps.strategy_service.fusion.signal_fusion import FusedSignal
from apps.strategy_service.main import (
    _apply_position_exit_overrides,
    _is_signal_blocked_by_hourly_trend,
)


def _signal(side: str, final_score: float = 0.4) -> FusedSignal:
    return FusedSignal(
        side=side,
        ta_score=0.0,
        sentiment_score=0.2,
        final_score=final_score,
        confidence=0.9,
        ta_only_mode=False,
    )


def test_apply_position_exit_overrides_forces_sell_on_strong_ta_weakness():
    signal, reason = _apply_position_exit_overrides(
        _signal("buy", final_score=0.35),
        ta_score=-0.20,
        hourly_trend="sideways",
        has_open_position=True,
    )

    assert signal.side == "sell"
    assert reason == "held_position_ta_exit"


def test_apply_position_exit_overrides_exits_on_mild_weakness_in_downtrend():
    signal, reason = _apply_position_exit_overrides(
        _signal("buy", final_score=0.38),
        ta_score=-0.08,
        hourly_trend="downtrend",
        has_open_position=True,
    )

    assert signal.side == "sell"
    assert reason == "held_position_downtrend_exit"


def test_apply_position_exit_overrides_holds_when_position_is_healthy():
    signal, reason = _apply_position_exit_overrides(
        _signal("buy", final_score=0.41),
        ta_score=0.05,
        hourly_trend="uptrend",
        has_open_position=True,
    )

    assert signal.side == "hold"
    assert reason == "held_position_hold"


def test_apply_position_exit_overrides_leaves_unheld_signal_unchanged():
    original = _signal("buy", final_score=0.41)
    signal, reason = _apply_position_exit_overrides(
        original,
        ta_score=-0.30,
        hourly_trend="downtrend",
        has_open_position=False,
    )

    assert signal.side == "buy"
    assert reason is None


def test_trend_filter_allows_sell_for_open_position_in_uptrend():
    assert _is_signal_blocked_by_hourly_trend(
        signal_side="sell",
        hourly_trend="uptrend",
        has_open_position=True,
    ) is False


def test_trend_filter_blocks_sell_without_position_in_uptrend():
    assert _is_signal_blocked_by_hourly_trend(
        signal_side="sell",
        hourly_trend="uptrend",
        has_open_position=False,
    ) is True
