from datetime import datetime, timezone

import pytest

from apps.execution_service.main import (
    _can_execute_signal,
    _default_protection_levels,
    _extract_exchange_position_rows,
    _extract_total_krw_balance,
    _filter_new_trades,
    _is_buy_signal_below_final_score_threshold,
    _is_manual_test_signal,
    _position_management_key,
    _resolve_manual_test_qty,
    _resolve_market_buy_krw_amount,
    _resolve_position_source,
    _position_source_from_strategy_managed,
    _resolve_protection_levels,
    _resolve_synced_position_protection_levels,
    _should_reset_loss_streak,
    _runtime_state_daily_pnl_key,
    _summarize_trades,
    _should_enforce_position_protection,
    _should_enforce_expected_profit_threshold,
)


def test_extract_exchange_position_rows_separates_krw_and_assets():
    balances = [
        {"currency": "KRW", "balance": "1000.5", "locked": "25.25", "avg_buy_price": "0"},
        {"currency": "BTC", "balance": "0.001", "locked": "0.0002", "avg_buy_price": "100000000"},
        {"currency": "ETH", "balance": "0", "locked": "0", "avg_buy_price": "3000000"},
    ]

    available_krw, positions = _extract_exchange_position_rows(balances)

    assert available_krw == 1000.5
    assert set(positions) == {"BTC"}
    assert positions["BTC"]["qty"] == pytest.approx(0.0012)
    assert positions["BTC"]["avg_entry_price"] == 100000000.0


def test_extract_total_krw_balance_includes_locked_krw():
    balances = [
        {"currency": "KRW", "balance": "1000.5", "locked": "25.25", "avg_buy_price": "0"},
        {"currency": "BTC", "balance": "0.001", "locked": "0.0002", "avg_buy_price": "100000000"},
    ]

    assert _extract_total_krw_balance(balances) == pytest.approx(1025.75)


def test_extract_exchange_position_rows_ignores_zero_balances():
    balances = [
        {"currency": "xrp", "balance": "0", "locked": "0", "avg_buy_price": "500"},
        {"currency": "ont", "balance": "10", "locked": "2", "avg_buy_price": "100.5"},
    ]

    available_krw, positions = _extract_exchange_position_rows(balances)

    assert available_krw == 0.0
    assert set(positions) == {"ONT"}
    assert positions["ONT"]["qty"] == 12.0
    assert positions["ONT"]["avg_entry_price"] == 100.5


def test_default_protection_levels_are_derived_from_entry_price():
    stop_loss, take_profit = _default_protection_levels(
        entry_price=100.0,
        stop_loss_pct=0.03,
        take_profit_pct=0.06,
    )

    assert stop_loss == pytest.approx(97.0)
    assert take_profit == pytest.approx(106.0)


def test_resolve_protection_levels_prefers_signal_values_and_falls_back_to_defaults():
    stop_loss, take_profit = _resolve_protection_levels(
        entry_price=100.0,
        suggested_stop_loss=None,
        suggested_take_profit=112.5,
        default_stop_loss_pct=0.03,
        default_take_profit_pct=0.06,
    )

    assert stop_loss == pytest.approx(97.0)
    assert take_profit == pytest.approx(112.5)


def test_synced_position_protection_disables_default_protection_for_external_holdings():
    stop_loss, take_profit = _resolve_synced_position_protection_levels(
        entry_price=100.0,
        default_stop_loss_pct=0.03,
        default_take_profit_pct=0.06,
        strategy_managed=False,
        external_stop_loss_enabled=False,
    )

    assert stop_loss is None
    assert take_profit is None


def test_position_protection_is_only_enforced_for_strategy_managed_positions():
    assert _should_enforce_position_protection("strategy", False, 97.0, None) is True
    assert _should_enforce_position_protection("external", False, 97.0, 106.0) is False
    assert _should_enforce_position_protection("strategy", False, None, None) is False


def test_synced_position_protection_can_enable_external_stop_loss_only():
    stop_loss, take_profit = _resolve_synced_position_protection_levels(
        entry_price=100.0,
        default_stop_loss_pct=0.03,
        default_take_profit_pct=0.06,
        strategy_managed=False,
        external_stop_loss_enabled=True,
    )

    assert stop_loss == pytest.approx(97.0)
    assert take_profit is None


def test_position_source_from_strategy_managed_maps_to_expected_values():
    assert _position_source_from_strategy_managed(True) == "strategy"
    assert _position_source_from_strategy_managed(False) == "external"


def test_position_source_override_can_promote_external_position_to_strategy():
    assert _resolve_position_source(False, "strategy") == "strategy"
    assert _resolve_position_source(True, "external") == "external"
    assert _resolve_position_source(False, None) == "external"


def test_position_management_key_uses_coin_id_namespace():
    assert _position_management_key(42) == "position.management.42"


def test_manual_test_signal_helpers():
    assert _is_manual_test_signal("manual-test") is True
    assert _is_manual_test_signal("strategy-v1") is False
    assert _can_execute_signal(
        strategy_id="manual-test",
        auto_trade_enabled=False,
        manual_test_mode_enabled=True,
    ) is True


def test_min_buy_final_score_only_rejects_regular_buy_signals():
    assert _is_buy_signal_below_final_score_threshold(
        side="buy",
        final_score=0.55,
        min_buy_final_score=0.60,
        manual_test_signal=False,
    ) is True
    assert _is_buy_signal_below_final_score_threshold(
        side="buy",
        final_score=0.55,
        min_buy_final_score=0.60,
        manual_test_signal=True,
    ) is False
    assert _is_buy_signal_below_final_score_threshold(
        side="sell",
        final_score=0.10,
        min_buy_final_score=0.60,
        manual_test_signal=False,
    ) is False
    assert _can_execute_signal(
        strategy_id="manual-test",
        auto_trade_enabled=False,
        manual_test_mode_enabled=False,
    ) is False
    assert _can_execute_signal(
        strategy_id="strategy-v1",
        auto_trade_enabled=True,
        manual_test_mode_enabled=False,
    ) is True


def test_expected_profit_threshold_only_applies_to_regular_buy_signals():
    assert _should_enforce_expected_profit_threshold("buy", False) is True
    assert _should_enforce_expected_profit_threshold("buy", True) is False
    assert _should_enforce_expected_profit_threshold("sell", False) is False


def test_resolve_manual_test_qty_uses_requested_buy_or_position_sell():
    assert _resolve_manual_test_qty(side="buy", suggested_qty=12.5, position_qty=0.0) == pytest.approx(12.5)
    assert _resolve_manual_test_qty(side="sell", suggested_qty=None, position_qty=3.0) == pytest.approx(3.0)
    assert _resolve_manual_test_qty(side="sell", suggested_qty=5.0, position_qty=3.0) == pytest.approx(3.0)


def test_runtime_state_daily_pnl_key_uses_kst_date():
    ts = datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc)
    assert _runtime_state_daily_pnl_key(ts) == "risk.daily_pnl.20260325"


def test_filter_new_trades_skips_existing_trade_uuids():
    trades = [
        {"uuid": "t1", "price": "100", "volume": "1", "funds": "100"},
        {"uuid": "t2", "price": "110", "volume": "2", "funds": "220"},
    ]

    result = _filter_new_trades(trades, {"t1"})

    assert result == [trades[1]]


def test_summarize_trades_uses_trade_funds_and_volume():
    trades = [
        {"uuid": "t1", "price": "100", "volume": "1", "funds": "100"},
        {"uuid": "t2", "price": "110", "volume": "2", "funds": "220"},
    ]

    executed_volume, executed_funds, avg_price, total_fee = _summarize_trades(trades)

    assert executed_volume == pytest.approx(3.0)
    assert executed_funds == pytest.approx(320.0)
    assert avg_price == pytest.approx(320.0 / 3.0)
    assert total_fee == pytest.approx(0.16)


def test_should_reset_loss_streak_only_when_stored_date_differs():
    assert _should_reset_loss_streak("20260324", "20260325") is True
    assert _should_reset_loss_streak("20260325", "20260325") is False
    assert _should_reset_loss_streak(None, "20260325") is False


def test_resolve_market_buy_krw_amount_clamps_to_fee_adjusted_balance():
    result = _resolve_market_buy_krw_amount(
        requested_qty=10.0,
        entry_price=2_000.0,
        available_krw=13_141.23,
        min_order_krw=5_000.0,
    )

    assert result == 13_134


def test_resolve_market_buy_krw_amount_rejects_if_clamped_below_minimum():
    result = _resolve_market_buy_krw_amount(
        requested_qty=10.0,
        entry_price=1_000.0,
        available_krw=4_999.0,
        min_order_krw=5_000.0,
    )

    assert result == 0
